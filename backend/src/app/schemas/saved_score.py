from datetime import date, datetime
from pydantic import BaseModel


class SavedScoreItem(BaseModel):
    score_id: str
    title: str
    week_of: date | None = None
    file_url: str
    file_uri: str | None = None
    download_url: str | None = None
    saved_at: datetime
    last_used_at: datetime | None = None
    use_count: int


class SavedScoreUploadRequest(BaseModel):
    title: str
    filename: str
    content_type: str | None = None


class SavedScoreUploadResponse(BaseModel):
    score_id: str
    upload_url: str
    download_url: str | None = None
    s3_key: str | None = None

class SavedScoreUseResponse(BaseModel):
    score_id: str
    use_count: int
    last_used_at: datetime


class SavedScoreApplyRequest(BaseModel):
    week_of: date
