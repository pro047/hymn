from datetime import date, datetime, timedelta
from typing import Literal

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
