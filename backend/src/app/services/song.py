import datetime as dt
import re
import unicodedata

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Score, SetItem, Song, Week


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


def has_usage_in_week(session: Session, *, song_id: str, week_of: dt.date | None) -> bool:
    return (
        session.query(Score.id)
        .filter(Score.song_id == song_id, Score.week_of == week_of)
        .first()
        is not None
    )


def replace_song_file(session: Session, song: Song, *, file_url: str, file_uri: str | None) -> None:
    song.file_url = file_url
    song.file_uri = file_uri


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


def _ensure_week(session: Session, week_of: dt.date) -> Week:
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
    score.week_of = week_of
    week = _ensure_week(session, week_of)
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
    else:
        session.add(
            SetItem(
                week_id=week.id,
                week_date=week.date,
                order_no=order_no + 1,
                score_id=score.id,
            )
        )
