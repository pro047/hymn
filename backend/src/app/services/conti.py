"""Weekly conti PDF: query the church's songs for a week, read their files,
and hand the images to conti_pdf.render_conti_pdf.

A read failure is never skipped — a song silently missing from the PDF has no
trace inside the file itself, and this domain has already been burned twice by
a failure nobody could see (SES 202-with-no-mail, saved-score snapshot drift).
So every entry either makes it into the PDF or the whole request fails.
"""

import logging
from dataclasses import dataclass
from datetime import date
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError  # type: ignore[import-not-found]
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.deps import ObjectReader
from app.models import Score, SetItem, Song
from app.services.conti_pdf import render_conti_pdf
from app.utils.s3 import ObjectNotReadable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContiEntry:
    score_id: str
    title: str
    file_uri: str | None


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
    rows = session.execute(
        select(Score.id, Song.title, Song.file_uri, order_no.label("order_no"))
        .join(Song, Song.id == Score.song_id)
        .where(Score.church_id == church_id, Score.week_of == week_of)
        .order_by(order_no.asc().nulls_last(), Score.created_at.asc(), Score.id.asc())
    ).all()

    if not rows:
        raise ContiEmpty()
    return [ContiEntry(score_id=row.id, title=row.title, file_uri=row.file_uri) for row in rows]


def build_week_conti_pdf(
    session: Session, *, church_id: str, week_of: date, read_object: ObjectReader
) -> bytes:
    entries = list_week_entries(session, church_id=church_id, week_of=week_of)

    images: list[Image.Image] = []
    for entry in entries:
        key = entry.file_uri
        # Same prefix _download_url signs on read (routes/score.py:39-40).
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

    return render_conti_pdf(images)
