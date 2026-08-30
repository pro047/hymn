import datetime as dt
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import get_current_user
from app.models import SavedScore, Score, Song, User
from app.schemas.saved_score import (
    SavedScoreApplyRequest,
    SavedScoreItem,
    SavedScoreUploadRequest,
    SavedScoreUploadResponse,
    SavedScoreUseResponse,
)
from app.services.song import attach_usage, get_or_reuse_song
from app.utils.files import extension_from_input
from app.utils.s3 import object_url, presign_get, presign_put

router = APIRouter(prefix="/me/saved-scores", tags=["saved-scores"])


def _normalize_week_date(week_of):
    if not week_of:
        return week_of
    return week_of - timedelta(days=(week_of.weekday() + 1) % 7)


def _download_url(file_uri: str | None) -> str | None:
    if not file_uri:
        return None
    if file_uri.startswith("scores/"):
        return presign_get(file_uri)
    return None


def _get_saved_score(session: Session, user_id: str, score_id: str) -> SavedScore | None:
    return (
        session.query(SavedScore)
        .filter(SavedScore.user_id == user_id, SavedScore.score_id == score_id)
        .first()
    )


@router.get("", response_model=list[SavedScoreItem])
def list_saved_scores(
    sort: Literal["recent", "frequent"] = Query(default="recent"),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    # Joined to Song, not read off the Score snapshot: a PATCH on *any* week's
    # usage rewrites the song's title/file (D3/D8), and the library would
    # otherwise keep serving the superseded title and the old S3 key — which
    # still resolves, so the disagreement is silent. Score.song_id is NOT NULL,
    # so the inner join cannot drop a saved row.
    query = (
        session.query(SavedScore, Score, Song)
        .join(Score, Score.id == SavedScore.score_id)
        .join(Song, Song.id == Score.song_id)
        .filter(SavedScore.user_id == user.id)
    )

    if sort == "frequent":
        query = query.order_by(
            desc(SavedScore.use_count),
            desc(SavedScore.last_used_at),
            desc(SavedScore.created_at),
        )
    else:
        query = query.order_by(desc(SavedScore.created_at))

    rows = query.all()
    return [
        SavedScoreItem(
            score_id=score.id,
            title=song.title,
            week_of=score.week_of,
            file_url=song.file_url,
            file_uri=song.file_uri,
            download_url=_download_url(song.file_uri),
            saved_at=saved.created_at,
            last_used_at=saved.last_used_at,
            use_count=saved.use_count,
        )
        for saved, score, song in rows
    ]


@router.post("/upload", response_model=SavedScoreUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_saved_score(
    payload: SavedScoreUploadRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    ext = extension_from_input(payload.filename, payload.content_type)
    key = f"scores/{user.church_id}/{uuid4()}.{ext}"

    song, created = get_or_reuse_song(
        session,
        church_id=user.church_id,
        title=payload.title,
        uploader_id=user.id,
        file_url=object_url(key),
        file_uri=key,
    )
    # Unlike POST /scores, a saved-score reupload is refused rather than
    # silently reused: SavedScoreUploadResponse has no room for a
    # reused_song/upload_url=null signal without becoming an ALLOWED_FILES
    # change, and 409 needs none since it is an HTTPException.
    if not created:
        raise HTTPException(
            status_code=409,
            detail="이미 등록된 곡입니다. 악보를 바꾸려면 [수정]을 사용해 주세요.",
        )

    score = Score(
        church_id=user.church_id,
        uploader_id=user.id,
        song_id=song.id,
        title=payload.title,
        week_of=None,
        file_url=object_url(key),
        file_uri=key,
        status="draft",
    )
    session.add(score)
    session.flush()
    session.add(SavedScore(user_id=user.id, score_id=score.id))
    session.commit()

    return SavedScoreUploadResponse(
        score_id=score.id,
        upload_url=presign_put(key, 900),
        download_url=presign_get(key),
        s3_key=key,
    )


@router.post("/{score_id}", status_code=status.HTTP_204_NO_CONTENT)
def save_score(
    score_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    score = session.get(Score, score_id)
    if not score or score.church_id != user.church_id:
        raise HTTPException(status_code=404, detail="Score not found")

    existing = _get_saved_score(session, user.id, score_id)
    if existing:
        return

    session.add(SavedScore(user_id=user.id, score_id=score_id))
    session.commit()
    return


@router.delete("/{score_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_saved_score(
    score_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    saved = _get_saved_score(session, user.id, score_id)
    if not saved:
        return

    session.delete(saved)
    session.commit()
    return


@router.post("/{score_id}/apply", response_model=SavedScoreUseResponse)
def apply_saved_score(
    score_id: str,
    payload: SavedScoreApplyRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    saved = _get_saved_score(session, user.id, score_id)
    if not saved:
        raise HTTPException(status_code=404, detail="Saved score not found")

    score = session.get(Score, score_id)
    if not score or score.church_id != user.church_id:
        raise HTTPException(status_code=404, detail="Score not found")

    normalized_week_of = _normalize_week_date(payload.week_of)
    attach_usage(session, score, normalized_week_of)

    saved.use_count += 1
    saved.last_used_at = dt.datetime.utcnow()

    session.commit()
    session.refresh(saved)

    return SavedScoreUseResponse(
        score_id=score.id,
        use_count=saved.use_count,
        last_used_at=saved.last_used_at,
    )
