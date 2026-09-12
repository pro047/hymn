import json
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Raised through ValueError, so pydantic emits it as `Value error, <text>`.
# The client strips that prefix and shows the rest, so it must be Korean.
PAST_WEEK_MESSAGE = "지난 주차에는 악보를 등록할 수 없습니다."


def current_week_start(today: date | None = None) -> date:
    """The Sunday that opens the week containing `today`.

    Matches _normalize_week_date in routes/score.py: a week is named by its
    Sunday. That is why the floor is this week's Sunday and not today — on a
    Thursday, the current week's own Sunday is already in the past by date,
    and rejecting it would block the week the caller is actually working on.
    """
    today = today or date.today()
    return today - timedelta(days=(today.weekday() + 1) % 7)


def reject_past_week(value: date | None) -> date | None:
    """Shared by create and update; both write the same column."""
    if value is not None and value < current_week_start():
        raise ValueError(PAST_WEEK_MESSAGE)
    return value


class ScoreCreate(BaseModel):
    # No church field, deliberately. The church comes from the caller's token,
    # so it cannot be chosen by the request — naming it here was what let an
    # unauthenticated caller write into any church, or invent a new one.
    # Length caps mirror the columns (title varchar(255), file_uri varchar(1024)).
    # Without them an oversized value passes validation and blows up at commit
    # as a DataError, which surfaces as a 500 instead of a 422.
    title: str = Field(..., min_length=1, max_length=255)
    week_of: date
    storage_type: Literal['s3', 'local']

    _reject_past_week = field_validator('week_of')(reject_past_week)
    # s3
    filename: str | None = None  # optional original filename for extension hint
    content_type: str | None = None
    note: str | None = None
    # local
    file_uri: str | None = Field(None, max_length=1024)

class ScoreCreateResponse(BaseModel):
    score_id: str
    upload_url: str | None = None
    download_url: str | None = None
    s3_key: str | None = None
    file_uri: str | None = None
    created_at: datetime | None = None
    # Defaults False so a consumer that does not know this key yet (an older
    # frontend build) keeps behaving as if every create were brand new.
    reused_song: bool = False

class ScoreResponse(BaseModel):
    id: str
    church_id: str
    week_of: date | None = None
    title: str
    file_url: str
    file_uri: str | None = None
    download_url: str | None = None
    created_at: datetime
    # None only for schema compatibility; the route always fills it in.
    song_id: str | None = None

class ScoreFileUploadRequest(BaseModel):
    # Required here, unlike ScoreCreate where the s3 branch checks it at
    # runtime: that model also serves the `local` branch, which has no filename.
    # This route has one branch and nothing to do without one.
    filename: str = Field(..., min_length=1, max_length=1024)
    content_type: str | None = None


class ScoreFileUploadResponse(BaseModel):
    upload_url: str
    s3_key: str


class ScoreUpdate(BaseModel):
    # Same caps as ScoreCreate: both write the same columns.
    title: str | None = Field(None, min_length=1, max_length=255)
    week_of: date | None = None
    file_uri: str | None = Field(None, max_length=1024)

    # Same rule on the way in through an edit: otherwise a score could be
    # created for a valid week and then moved into a past one.
    _reject_past_week = field_validator('week_of')(reject_past_week)


# The editor's document is stored opaquely, so nothing here can bound it by
# counting fields. It is bounded by its serialized size instead: freehand
# strokes are a point list, and a long session on a large sheet is tens of KB
# against production's 137 KB median *image*. 1 MB leaves that an order of
# magnitude of headroom while keeping a runaway document out of a row that
# every conti read touches. Refused at the schema, so an oversized body never
# reaches the transaction.
MAX_EDIT_DOC_BYTES = 1024 * 1024


class ScoreEditUploadResponse(BaseModel):
    upload_url: str
    s3_key: str


class ScoreEditRequest(BaseModel):
    """A finished edit: the flattened sheet, and the objects it was flattened
    from.

    Both are required together. Storing the picture without the document would
    leave a week showing markings that can never be moved or taken off again,
    which is the whole reason the document exists.
    """

    edited_file_uri: str = Field(..., min_length=1, max_length=1024)
    edit_doc: dict[str, Any]

    @field_validator("edit_doc")
    @classmethod
    def _reject_oversized_doc(cls, value: dict[str, Any]) -> dict[str, Any]:
        # separators= matches no whitespace, the same way the JSON reaches the
        # column: measuring the pretty-printed form would refuse documents that
        # fit.
        size = len(json.dumps(value, separators=(",", ":")).encode())
        if size > MAX_EDIT_DOC_BYTES:
            raise ValueError("편집 내용이 너무 큽니다.")
        return value


class ScoreEditResponse(BaseModel):
    """What the editor needs to open a sheet, and what it gets back on save.

    source_image_url is the *song's* file, signed fresh on every read. It is
    the canvas background, and edit_doc is replayed over it. Two consequences
    that are easy to get wrong:

    - Not the edited sheet. That one already has these objects painted into
      it, so using it as the background would draw every marking twice.
    - Not stored in edit_doc either. A presigned URL expires; a document
      holding one would reopen to a broken background once it did.
    """

    edited_file_uri: str | None = None
    edit_doc: dict[str, Any] | None = None
    source_image_url: str | None = None
