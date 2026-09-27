from datetime import date, datetime

from pydantic import BaseModel, Field


class SavedScoreItem(BaseModel):
    song_id: str
    title: str
    file_url: str
    file_uri: str | None = None
    download_url: str | None = None
    saved_at: datetime
    # Read off the song's usages across the church, however each was filed.
    last_week_of: date | None = None
    use_count: int


class SavedScoreUploadRequest(BaseModel):
    # Same cap as ScoreCreate.title: writes the same scores.title varchar(255).
    title: str = Field(..., min_length=1, max_length=255)
    filename: str
    content_type: str | None = None


class SavedScoreUploadResponse(BaseModel):
    song_id: str
    upload_url: str
    download_url: str | None = None
    s3_key: str | None = None

class SavedScoreUseResponse(BaseModel):
    song_id: str
    # The usage the apply filed.
    score_id: str


class SavedScoreApplyRequest(BaseModel):
    week_of: date
