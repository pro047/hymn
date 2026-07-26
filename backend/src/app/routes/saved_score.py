import datetime as dt
from datetime import timedelta
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from jose import JWTError
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import SavedScore, Score, SetItem, User, Week
from app.schemas.saved_score import (
    SavedScoreApplyRequest,
    SavedScoreItem,
    SavedScoreUploadRequest,
    SavedScoreUploadResponse,
    SavedScoreUseResponse,
)
from app.services.auth import decode_token, parse_bearer_token
from app.utils.files import extension_from_input
from app.utils.s3 import object_url, presign_get, presign_put

router = APIRouter(prefix="/me/saved-scores", tags=["saved-scores"])


def _normalize_week_date(week_of):
    if not week_of:
        return week_of
    return week_of - timedelta(days=(week_of.weekday() + 1) % 7)


def _ensure_week(session: Session, week_of):
    week = session.query(Week).filter(Week.date == week_of).first()
    if not week:
        week = Week(date=week_of)
        session.add(week)
        session.flush()
    return week


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


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    session: Session = Depends(get_session),
) -> User:
    try:
        token = parse_bearer_token(authorization)
        claims = decode_token(token)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None

    if claims.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token claims")

    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.get("", response_model=list[SavedScoreItem])
def list_saved_scores(
    sort: Literal["recent", "frequent"] = Query(default="recent"),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    query = (
        session.query(SavedScore, Score)
        .join(Score, Score.id == SavedScore.score_id)
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
            title=score.title,
            week_of=score.week_of,
            file_url=score.file_url,
            file_uri=score.file_uri,
            download_url=_download_url(score.file_uri),
            saved_at=saved.created_at,
            last_used_at=saved.last_used_at,
            use_count=saved.use_count,
        )
        for saved, score in rows
    ]


@router.post("/upload", response_model=SavedScoreUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_saved_score(
    payload: SavedScoreUploadRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    ext = extension_from_input(payload.filename, payload.content_type)
    key = f"scores/{user.church_id}/{uuid4()}.{ext}"
    score = Score(
        church_id=user.church_id,
        uploader_id=user.id,
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
    week = _ensure_week(session, normalized_week_of)
    score.week_of = normalized_week_of

    items = session.query(SetItem).filter(SetItem.score_id == score.id).all()
    order_no = (
        session.query(func.coalesce(func.max(SetItem.order_no), 0))
        .filter(SetItem.week_id == week.id, SetItem.week_date == week.date)
        .scalar()
        or 0
    )

    if items:
        for item in items:
            order_no += 1
            item.week_id = week.id
            item.week_date = week.date
            item.order_no = order_no
    else:
        session.add(
            SetItem(
                week_id=week.id,
                week_date=week.date,
                order_no=order_no + 1,
                score_id=score.id,
            )
        )

    saved.use_count += 1
    saved.last_used_at = dt.datetime.utcnow()

    session.commit()
    session.refresh(saved)

    return SavedScoreUseResponse(
        score_id=score.id,
        use_count=saved.use_count,
        last_used_at=saved.last_used_at,
    )
