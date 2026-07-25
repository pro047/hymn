from datetime import timedelta
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Church, Score, SetItem, Week
from app.schemas.score import ScoreCreate, ScoreCreateResponse, ScoreResponse, ScoreUpdate
from app.utils.files import extension_from_input
from app.utils.s3 import object_url, presign_get, presign_put

router = APIRouter()

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

@router.post('/scores', response_model=ScoreCreateResponse)
def create_score(payload: ScoreCreate, session: Session = Depends(get_session)):
    normalized_week_of = _normalize_week_date(payload.week_of)
    church_id = payload.church_id
    if not church_id and payload.church_name:
        church = session.query(Church).filter(Church.name == payload.church_name).first()
        if not church:
            church = Church(name=payload.church_name)
            session.add(church)
            session.commit()
            session.refresh(church)
        church_id = church.id
    if not church_id:
        raise HTTPException(400, 'church_id or church_name required')
    if payload.church_id:
        exists = session.query(Church.id).filter(Church.id == payload.church_id).first()
        if not exists:
            raise HTTPException(400, 'church_id not found')
    week = _ensure_week(session, normalized_week_of)
    if payload.storage_type == 's3':
        if not payload.filename:
            raise HTTPException(400, 'filename required for s3')
        ext = extension_from_input(payload.filename, payload.content_type)
        key = f"scores/.../{uuid4()}.{ext}"
        score = Score(
            church_id=church_id,
            title=payload.title,
            week_of=normalized_week_of,
            file_url=object_url(key),
            file_uri=key,
            status='draft'
        )
        session.add(score)
        session.flush()
        order_no = session.query(func.coalesce(func.max(SetItem.order_no), 0)).filter(
            SetItem.week_id == week.id,
            SetItem.week_date == week.date,
        ).scalar()
        session.add(SetItem(
            week_id=week.id,
            week_date=week.date,
            order_no=(order_no or 0) + 1,
            score_id=score.id,
        ))
        session.commit()
        session.refresh(score)
        return {
            "score_id": score.id,
            "upload_url": presign_put(key, 900),
            "download_url": presign_get(key),
            "s3_key": key,
        }
    
    if not payload.file_uri:
        raise HTTPException(400, 'file_uri required for local')
    score = Score(
        church_id=church_id,
        title=payload.title,
        week_of=normalized_week_of,
        file_url=payload.file_uri,
        file_uri=payload.file_uri,
        status='draft'
    )
    session.add(score)
    session.flush()
    order_no = session.query(func.coalesce(func.max(SetItem.order_no), 0)).filter(
        SetItem.week_id == week.id,
        SetItem.week_date == week.date,
    ).scalar()
    session.add(SetItem(
        week_id=week.id,
        week_date=week.date,
        order_no=(order_no or 0) + 1,
        score_id=score.id,
    ))
    session.commit()
    session.refresh(score)
    return {
        "score_id": score.id,
        "church_id": score.church_id,
        "week_of": score.week_of,
        "title": score.title,
        "file_uri": score.file_uri,
        "created_at": score.created_at
    }

@router.get("/scores", response_model=list[ScoreResponse])
def list_scores(session: Session = Depends(get_session)):
    scores = session.query(Score).filter(Score.week_of.is_not(None)).order_by(Score.created_at.asc()).all()
    return [
        ScoreResponse(
            id=s.id,
            church_id=s.church_id,
            week_of=s.week_of,
            title=s.title,
            file_url=s.file_url,
            file_uri=s.file_uri,
            download_url=_download_url(s.file_uri),
            created_at=s.created_at,
        )
        for s in scores
    ]

@router.get("/scores/{score_id}", response_model=ScoreResponse)
def get_score(score_id: str, session: Session = Depends(get_session)):
    score = session.get(Score, score_id)
    if not score:
        raise HTTPException(404, "Score not found")
    return ScoreResponse(
        id=score.id,
        church_id=score.church_id,
        week_of=score.week_of,
        title=score.title,
        file_url=score.file_url,
        file_uri=score.file_uri,
        download_url=_download_url(score.file_uri),
        created_at=score.created_at
    )

@router.patch("/scores/{score_id}", response_model=ScoreResponse)
def update_score(score_id: str, payload: ScoreUpdate, session: Session = Depends(get_session)):
    score = session.get(Score, score_id)
    if not score:
        raise HTTPException(404, "Score not found")
    
    if payload.title is not None:
        score.title = payload.title
    if payload.week_of is not None:
        normalized_week_of = _normalize_week_date(payload.week_of)
        if normalized_week_of != score.week_of:
            score.week_of = normalized_week_of
            week = _ensure_week(session, normalized_week_of)
            items = session.query(SetItem).filter(SetItem.score_id == score.id).all()
            if items:
                order_no = session.query(func.coalesce(func.max(SetItem.order_no), 0)).filter(
                    SetItem.week_id == week.id,
                    SetItem.week_date == week.date,
                ).scalar() or 0
                for item in items:
                    order_no += 1
                    item.week_id = week.id
                    item.week_date = week.date
                    item.order_no = order_no
    if payload.file_uri is not None:
        score.file_uri = payload.file_uri
        score.file_url = payload.file_uri

    session.commit()
    session.refresh(score)

    return ScoreResponse(
        id=score.id,
        church_id=score.church_id,
        week_of=score.week_of,
        title=score.title,
        file_url=score.file_url,
        file_uri=score.file_uri,
        download_url=_download_url(score.file_uri),
        created_at=score.created_at
    )

@router.delete('/scores/{score_id}', status_code=204)
def delete_score(score_id: str, session: Session = Depends(get_session)):
    score = session.get(Score, score_id)
    if not score:
        raise HTTPException(404, "Score not found")
    session.delete(score)
    session.commit()
    return
