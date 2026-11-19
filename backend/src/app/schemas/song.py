from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.score import reject_past_week


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


class SongUpdate(BaseModel):
    # Same bounds as ScoreUpdate so the two edit paths accept the same input.
    title: str | None = Field(None, min_length=1, max_length=255)
    file_uri: str | None = Field(None, max_length=1024)

    # Unlike ScoreUpdate, an empty body would be a silent no-op here.
    @model_validator(mode="after")
    def _require_a_change(self):
        if self.title is None and self.file_uri is None:
            raise ValueError("바꿀 제목이나 파일을 보내 주세요.")
        return self


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

    # A Sunday already gone by is a mis-click, not a filing: in production no
    # score was ever filed after its Sunday.
    _reject_past_week = field_validator("week_of")(reject_past_week)


class SongUsageResponse(BaseModel):
    song_id: str
    # The usage the placement filed.
    score_id: str
