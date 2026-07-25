from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ScoreCreate(BaseModel):
    title: str = Field(..., max_length=255)
    church_id: str | None = None
    church_name: str | None = None
    week_of: date
    storage_type: Literal['s3', 'local']
    # s3
    filename: Optional[str] = None  # optional original filename for extension hint
    content_type: Optional[str] = None
    note: Optional[str] = None
    # local
    file_uri: str | None = None

class ScoreCreateResponse(BaseModel):
    score_id: str
    upload_url: str | None = None
    download_url: str | None = None
    s3_key: str | None = None
    file_uri: str | None = None
    created_at: datetime | None = None

class ScoreResponse(BaseModel):
    id: str
    church_id: str
    week_of: date | None = None
    title: str
    file_url: str
    file_uri: str | None = None
    download_url: str | None = None
    created_at: datetime

class ScoreUpdate(BaseModel):
    title: str | None = None
    week_of: date | None = None
    file_uri: str | None = None
