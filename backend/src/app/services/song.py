import datetime as dt
import re
import unicodedata

from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.models import Score, SetItem, Song, Week
from app.services.score_edit import clear_edit


class SongTitleTaken(Exception):
    """Raised by rename_song when the target title already names another song
    in the same church."""


def normalize_title(title: str) -> str:
    """The matching key for a title: NFC, then every run of whitespace gone,
    then lowercased.

    \\s rather than a literal space so a full-width space (U+3000) or an NBSP
    pasted in from elsewhere still collapses — both show up in real input.
    This is the one place the rule is computed; the migration keeps its own
    copy rather than importing this, since a migration has to stay pinned to
    the rule it ran with.
    """
    folded = unicodedata.normalize("NFC", title)
    collapsed = re.sub(r"\s+", "", folded)
    return collapsed.lower()


def find_song(session: Session, *, church_id: str, title: str) -> Song | None:
    return (
        session.query(Song)
        .filter(Song.church_id == church_id, Song.title_key == normalize_title(title))
        .first()
    )


def get_or_reuse_song(
    session: Session,
    *,
    church_id: str,
    title: str,
    uploader_id: str | None,
    file_url: str,
    file_uri: str | None,
) -> tuple[Song, bool]:
    """(song, created). If a song with this title already exists in the
    church, its file is left untouched and the caller must not issue a
    presign — reuse is the default path, so accidentally overwriting the file
    a church has been using for months takes a deliberate PATCH, not a
    same-titled upload.
    """
    existing = find_song(session, church_id=church_id, title=title)
    if existing is not None:
        return existing, False

    song = Song(
        church_id=church_id,
        uploader_id=uploader_id,
        title=title.strip(),
        title_key=normalize_title(title),
        file_url=file_url,
        file_uri=file_uri,
    )
    session.add(song)
    session.flush()
    return song, True


def library_rows(
    session: Session,
    *,
    church_id: str,
    song_id: str | None = None,
) -> list[tuple[Song, int, dt.date | None]]:
    """(song, use_count, last_week_of) for the church's songs, newest first.

    A usage counts only when it has a week: usages without one are legacy
    library-upload drafts. Shared by the list and the edit answer so the two
    cannot drift apart. song_id narrows to one song.
    """
    usage = (
        session.query(
            Score.song_id.label("song_id"),
            func.count(Score.id).label("use_count"),
            func.max(Score.week_of).label("last_week_of"),
        )
        .filter(Score.church_id == church_id, Score.week_of.is_not(None))
        .group_by(Score.song_id)
        .subquery()
    )
    use_count = func.coalesce(usage.c.use_count, 0)
    query = (
        session.query(Song, use_count, usage.c.last_week_of)
        .outerjoin(usage, usage.c.song_id == Song.id)
        .filter(Song.church_id == church_id)
    )
    if song_id is not None:
        query = query.filter(Song.id == song_id)
    return [tuple(row) for row in query.order_by(desc(Song.created_at), Song.id).all()]


def has_usage_in_week(session: Session, *, song_id: str, week_of: dt.date | None) -> bool:
    return (
        session.query(Score.id)
        .filter(Score.song_id == song_id, Score.week_of == week_of)
        .first()
        is not None
    )


def add_usage(
    session: Session,
    song: Song,
    *,
    church_id: str,
    uploader_id: str,
    week_of: dt.date,
) -> Score:
    """A new usage of `song` filed under `week_of`, set item included.

    Title and file are the usage's snapshot of the song's own.
    """
    score = Score(
        church_id=church_id,
        uploader_id=uploader_id,
        song_id=song.id,
        title=song.title,
        week_of=week_of,
        file_url=song.file_url,
        file_uri=song.file_uri,
        status="draft",
    )
    session.add(score)
    session.flush()
    attach_usage(session, score, week_of)
    return score


def replace_song_file(session: Session, song: Song, *, file_url: str, file_uri: str | None) -> None:
    song.file_url = file_url
    song.file_uri = file_uri


def rename_usage(score: Score, new_title: str) -> None:
    """Renames one week's copy only. The song and every other week keep their
    titles, so there is no collision to check."""
    score.title = new_title.strip()


def replace_usage_file(score: Score, *, file_url: str, file_uri: str) -> None:
    """Points one week's copy at a new file. The edit was drawn on the sheet
    being replaced, so it goes too; other weeks' edits are their own sheets."""
    score.file_url = file_url
    score.file_uri = file_uri
    clear_edit(score)


def heal_song_file(session: Session, song: Song, *, file_url: str, file_uri: str) -> int:
    """Gives a song whose file never arrived a new one, and moves the weeks
    that were still holding the dead key along with it.

    Matched on the old key rather than on song_id alone: a week whose file was
    replaced through PATCH /scores holds a key that is alive, and healing must
    not overwrite it. Edit columns are left alone for the same reason.
    Returns how many weeks moved.
    """
    old = song.file_uri
    replace_song_file(session, song, file_url=file_url, file_uri=file_uri)
    if old is None:
        return 0
    rows = (
        session.query(Score)
        .filter(Score.song_id == song.id, Score.file_uri == old)
        .all()
    )
    for row in rows:
        row.file_url = file_url
        row.file_uri = file_uri
    return len(rows)


def rename_song(session: Session, song: Song, new_title: str) -> None:
    """Renames a song for every week it was used. Raises SongTitleTaken if the
    new title already names a different song in the same church — merging two
    songs is out of scope, and title/title_key are updated together so the
    display and the matching key never drift apart.
    """
    new_key = normalize_title(new_title)
    if new_key != song.title_key:
        collision = (
            session.query(Song.id)
            .filter(Song.church_id == song.church_id, Song.title_key == new_key, Song.id != song.id)
            .first()
        )
        if collision is not None:
            raise SongTitleTaken(new_title)
    song.title = new_title.strip()
    song.title_key = new_key


def normalize_week_date(week_of: dt.date | None) -> dt.date | None:
    """Snap a date back to the Sunday that starts its week.

    Every write path files a Score under the normalized date, so every read
    path has to normalize too or it asks about a week that cannot exist in
    the table. This lives here rather than in a router because three routers
    now need it, and a private function imported sideways out of one of them
    is the pattern deps.py already warns about.
    """
    if not week_of:
        return week_of
    return week_of - dt.timedelta(days=(week_of.weekday() + 1) % 7)


def ensure_week(session: Session, week_of: dt.date) -> Week:
    week = session.query(Week).filter(Week.date == week_of).first()
    if not week:
        week = Week(date=week_of)
        session.add(week)
        session.flush()
    return week


def attach_usage(session: Session, score: Score, week_of: dt.date) -> None:
    """Files `score` under the given week: sets week_of, ensures the Week row,
    and either inserts a new SetItem or moves the score's existing one(s) to
    the end of the new week's order. Callers must already have normalized
    week_of (see _normalize_week_date in the routers) — this only handles the
    set-membership side, the same division of labor the routes used before.
    """
    # Nor does the edited sheet, for the same reason as the page break below:
    # it was drawn for the service this row used to be filed under, and the
    # markings on it ("3부", a repeat someone agreed on that morning) describe
    # that Sunday. Left in place it would show up on a week nobody drew it
    # for, and nothing on screen would say why.
    #
    # Only when the week actually changes, and the check lives here rather
    # than in the callers because they do not agree: update_score already
    # guards this call, and the other callers file a row that has no week yet.
    if score.week_of != week_of:
        clear_edit(score)
    score.week_of = week_of
    week = ensure_week(session, week_of)
    items = session.query(SetItem).filter(SetItem.score_id == score.id).all()
    order_no = (
        session.query(func.coalesce(func.max(SetItem.order_no), 0))
        .filter(SetItem.week_id == week.id, SetItem.week_date == week.date)
        .scalar()
        or 0
    )
    if items:
        for item in items:
            order_no += 1
            item.week_id = week.id
            item.week_date = week.date
            item.order_no = order_no
            # The break does not travel with the song. It describes where a
            # page was cut in the week it was set in — the leader arranged
            # *that* conti — and this row is being filed at the end of a
            # different week, next to songs nobody rearranged. Carried over,
            # it would cut a page in the new week's preview and PDF with
            # nothing on screen explaining why, and set_week_order only clears
            # a stale flag for position 1, so it would survive until someone
            # reordered that week.
            item.starts_new_page = False
    else:
        session.add(
            SetItem(
                week_id=week.id,
                week_date=week.date,
                order_no=order_no + 1,
                score_id=score.id,
            )
        )
