from datetime import date, datetime

from pydantic import BaseModel, Field


class SongLibraryItem(BaseModel):
    song_id: str
    title: str
    file_url: str
    file_uri: str | None = None
    download_url: str | None = None
    created_at: datetime
    # Read off the song's usages across the church, however each was filed.
    last_week_of: date | None = None
    use_count: int


class SongUploadRequest(BaseModel):
    # Same cap as songs.title varchar(255).
    title: str = Field(..., min_length=1, max_length=255)
    filename: str
    content_type: str | None = None


class SongUploadResponse(BaseModel):
    song_id: str
    upload_url: str
    download_url: str | None = None
    s3_key: str | None = None


class SongUsageRequest(BaseModel):
    week_of: date


class SongUsageResponse(BaseModel):
    song_id: str
    # The usage the placement filed.
    score_id: str
