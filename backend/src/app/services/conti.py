"""Weekly conti PDF: query the church's songs for a week, read their files,
and hand the images to conti_pdf.render_conti_pdf.

A read failure is never skipped — a song silently missing from the PDF has no
trace inside the file itself, and this domain has already been burned twice by
a failure nobody could see (SES 202-with-no-mail, saved-score snapshot drift).
So every entry either makes it into the PDF or the whole request fails.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError  # type: ignore[import-not-found]
from sqlalchemy import false as sa_false
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import ObjectReader
from app.models import Score, SetItem, Song
from app.services.conti_pdf import chunk_pages, render_conti_pdf
from app.services.song import ensure_week
from app.utils.s3 import ObjectNotReadable

logger = logging.getLogger(__name__)

# MAX_OBJECT_BYTES caps the compressed file; this caps what it decodes to.
# Pillow's own DecompressionBombError only fires above ~178M pixels, so a
# 20 MB PNG can legally expand to ~89M pixels = 268 MB as RGB, and flattening
# alpha makes two more copies of that — on a 2 GiB t4g.small shared with
# nginx and the frontend. 40M pixels is ~4.5x the largest sheet a score
# plausibly needs (A4 at 300dpi is 8.7M) and ~34x production's largest
# measured image (1080x1080).
MAX_IMAGE_PIXELS = 40_000_000


@dataclass(frozen=True)
class ContiEntry:
    score_id: str
    title: str
    file_uri: str | None
    starts_new_page: bool = False


class ContiEmpty(Exception):
    """No score is filed for this church in this week."""


class ContiFileUnreadable(Exception):
    """This entry's file could not be fetched: missing key, foreign key, or a
    genuine S3 failure. The three are folded together — none of them tells
    the caller anything they can act on beyond "re-upload this song's file".
    """

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__(title)


class ContiOrderMismatch(Exception):
    """The submitted order does not name exactly this week's songs.

    Rejected rather than reconciled: a partial list makes the position of the
    songs it leaves out undefined, and silently filing them at the end would
    reorder a conti the leader never touched.
    """


class ContiFileNotAnImage(Exception):
    """This entry's bytes are not an image Pillow can open (e.g. a PDF)."""

    def __init__(self, title: str) -> None:
        self.title = title
        super().__init__(title)


def _flatten_onto_white(image: Image.Image) -> Image.Image:
    """Drop alpha by compositing onto white, not by discarding the channel.

    convert("RGB") on an RGBA/LA image keeps whatever RGB sits under the
    transparent pixels, which for a typical transparent export is black — a
    scanned score would come out as a solid black half-sheet with nothing in
    the pipeline flagging it. 7 of the 85 production songs already carry an
    alpha channel (measured 2026-09-06; none of them has a transparent pixel
    today, so this is prevention, not a live bug).
    """
    if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(canvas, rgba).convert("RGB")
    return image.convert("RGB")


def list_week_entries(session: Session, *, church_id: str, week_of: date) -> list[ContiEntry]:
    """This church's songs for this week, ordered for a stable set list.

    Score is the driving table and SetItem is a correlated scalar subquery
    rather than a join: a join would duplicate rows for a Score with more
    than one SetItem (attach_usage can move every existing SetItem onto a new
    week) and would drop a Score that has none at all, which is still a song
    filed for this week.
    """
    order_no = (
        select(func.min(SetItem.order_no))
        .where(SetItem.score_id == Score.id, SetItem.week_date == week_of)
        .scalar_subquery()
    )
    # bool_or, not the flag of whichever row min(order_no) came from: a Score
    # can carry more than one SetItem for a week (attach_usage moves every
    # existing item onto the new week), and picking "a row" would make the
    # answer depend on which one the planner returned. One item asking for a
    # break is enough. NULL (no SetItem at all) folds to False.
    starts_new_page = (
        select(func.coalesce(func.bool_or(SetItem.starts_new_page), sa_false()))
        .where(SetItem.score_id == Score.id, SetItem.week_date == week_of)
        .scalar_subquery()
    )
    rows = session.execute(
        select(
            Score.id,
            Song.title,
            Song.file_uri,
            order_no.label("order_no"),
            starts_new_page.label("starts_new_page"),
        )
        .join(Song, Song.id == Score.song_id)
        .where(Score.church_id == church_id, Score.week_of == week_of)
        .order_by(order_no.asc().nulls_last(), Score.created_at.asc(), Score.id.asc())
    ).all()

    if not rows:
        raise ContiEmpty()
    return [
        ContiEntry(
            score_id=row.id,
            title=row.title,
            file_uri=row.file_uri,
            starts_new_page=bool(row.starts_new_page),
        )
        for row in rows
    ]


def build_week_conti_pdf(
    session: Session, *, church_id: str, week_of: date, read_object: ObjectReader
) -> bytes:
    entries = list_week_entries(session, church_id=church_id, week_of=week_of)

    images: list[Image.Image] = []
    for entry in entries:
        key = entry.file_uri
        # Same prefix presign_score_download signs on read (utils/s3.py).
        # Not the tighter scores/{church_id}/ that writes use: 60 of the 85
        # production songs still carry keys minted before ece1e92, whose
        # literal placeholder segment makes them scores/.../{uuid}.{ext}.
        # Requiring the church segment here would 502 27 of 32 weeks
        # (measured 2026-09-06). Church scoping is enforced by the query
        # above; this gate only keeps a NULL or off-bucket path out of
        # read_object.
        if not key or not key.startswith("scores/"):
            logger.warning(
                "conti pdf: refusing to read key week_of=%s church_id=%s score_id=%s "
                "key=%s reason=missing_or_unexpected_prefix",
                week_of,
                church_id,
                entry.score_id,
                key,
            )
            raise ContiFileUnreadable(entry.title)

        try:
            raw = read_object(key)
        except ObjectNotReadable as exc:
            logger.warning(
                "conti pdf: object read failed week_of=%s church_id=%s score_id=%s key=%s cause=%s",
                week_of,
                church_id,
                entry.score_id,
                key,
                exc.__cause__,
            )
            raise ContiFileUnreadable(entry.title) from exc

        try:
            image = Image.open(BytesIO(raw))
        except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ContiFileNotAnImage(entry.title) from exc
        except OSError as exc:
            # Some plugins raise a bare OSError out of _open(); Image.open
            # only swallows SyntaxError/IndexError/TypeError/struct.error
            # itself. Without this a corrupt header of a recognized format
            # escapes as a 500 instead of the 409 this path defines.
            raise ContiFileNotAnImage(entry.title) from exc

        if image.width * image.height > MAX_IMAGE_PIXELS:
            logger.warning(
                "conti pdf: image too large to decode week_of=%s church_id=%s score_id=%s "
                "key=%s pixels=%d",
                week_of,
                church_id,
                entry.score_id,
                key,
                image.width * image.height,
            )
            raise ContiFileUnreadable(entry.title)

        try:
            image.load()
            images.append(_flatten_onto_white(ImageOps.exif_transpose(image)))
        except (UnidentifiedImageError, Image.DecompressionBombError) as exc:
            raise ContiFileNotAnImage(entry.title) from exc
        except OSError as exc:
            # A truncated upload raises OSError from load() on an otherwise
            # valid image. That is "fetch it again", not "your file is wrong",
            # so it takes the 502 path rather than the 409 one.
            logger.warning(
                "conti pdf: image decode failed week_of=%s church_id=%s score_id=%s key=%s cause=%s",
                week_of,
                church_id,
                entry.score_id,
                key,
                exc,
            )
            raise ContiFileUnreadable(entry.title) from exc

    return render_conti_pdf(images, [entry.starts_new_page for entry in entries])


@dataclass(frozen=True)
class ContiOrderItem:
    score_id: str
    starts_new_page: bool


def set_week_order(
    session: Session, *, church_id: str, week_of: date, items: Sequence[ContiOrderItem]
) -> None:
    """Rewrite this week's running order and page breaks.

    The submitted list must name this week's songs exactly once each — see
    ContiOrderMismatch. order_no is renumbered 1..N from the list's own
    order, so the client sends a sequence, not numbers it had to compute.

    A Score filed for the week with no SetItem row (rows predating
    8e6c1cda8a6b were never backfilled) gets one here, otherwise its position
    would have nowhere to live.
    """
    rows = session.execute(
        select(Score.id).where(Score.church_id == church_id, Score.week_of == week_of)
    ).all()
    week_score_ids = {row.id for row in rows}
    submitted = [item.score_id for item in items]
    if len(submitted) != len(set(submitted)) or set(submitted) != week_score_ids:
        raise ContiOrderMismatch()

    week = ensure_week(session, week_of)
    existing: dict[str, list[SetItem]] = {}
    for set_item in (
        session.query(SetItem)
        .filter(SetItem.week_date == week_of, SetItem.score_id.in_(week_score_ids))
        .all()
    ):
        existing.setdefault(set_item.score_id, []).append(set_item)

    for position, item in enumerate(items, start=1):
        # Every row for the score, not just one: attach_usage moves all of a
        # score's SetItems onto a week, and the read path folds duplicates
        # with min(order_no)/bool_or(starts_new_page). Updating one would let
        # min() keep a stale number, so a reorder appears not to take, and
        # bool_or() keep a page break the leader just cleared.
        rows = existing.get(item.score_id)
        if not rows:
            rows = [SetItem(week_id=week.id, week_date=week.date, score_id=item.score_id, order_no=position)]
            session.add(rows[0])
        for set_item in rows:
            set_item.week_id = week.id
            set_item.week_date = week.date
            set_item.order_no = position
            # The first song's flag is forced off, not stored as sent:
            # chunk_pages ignores a break there (it already starts a page), so
            # keeping it would leave a value that changes nothing, is invisible
            # on screen, and cannot be cleared — moving a broken-before song to
            # the front is exactly how a leader lands in that state.
            set_item.starts_new_page = item.starts_new_page and position > 1


def list_week_pages(
    session: Session, *, church_id: str, week_of: date
) -> list[list[ContiEntry]]:
    """This week's songs already grouped into the pages the PDF will make.

    The split is computed here, not in the browser: chunk_pages is the
    renderer's own rule, and a second copy of it in JS would drift from what
    the PDF actually does — which is exactly what the preview exists to show.
    An empty week is an empty list, not ContiEmpty; the editing screen has to
    render "nothing filed yet".
    """
    try:
        entries = list_week_entries(session, church_id=church_id, week_of=week_of)
    except ContiEmpty:
        return []
    return chunk_pages(entries, [entry.starts_new_page for entry in entries])
