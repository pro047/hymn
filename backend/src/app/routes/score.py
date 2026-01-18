from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Score
from app.schemas.score import ScoreCreate, ScoreCreateResponse, ScoreResponse, ScoreUpdate
from app.utils.files import extension_from_input
from app.utils.s3 import presign_get, presign_put

router = APIRouter()

@router.post('/scores', response_model=ScoreCreateResponse)
def create_score(payload: ScoreCreate, session: Session = Depends(get_session)):
    if payload.storage_type == 's3':
        if not payload.filename:
            raise HTTPException(400, 'filename required for s3')
        ext = extension_from_input(payload.filename, payload.content_type)
        key = f"scores/.../{uuid4()}.{ext}"
        score = Score(
            church_id=payload.church_id,
            title=payload.title,
            week_of=payload.week_of,
            file_url=key,
            status='draft'
        )
        session.add(score)
        session.commit()
        session.refresh(score)
        return {
            "score_id": score.id,
            "upload_url": presign_put(key, 900, payload.content_type),
            "download_url": presign_get(key),
            "s3_key": key,
        }
    
    if not payload.file_uri:
        raise HTTPException(400, 'file_uri required for local')
    score = Score(
        church_id=payload.church_id,
        title=payload.title,
        week_of=payload.week_of,
        file_url=payload.file_uri,
        file_uri=payload.file_uri,
        status='draft'
    )
    session.add(score)
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
    scores = session.query(Score).order_by(Score.created_at.desc()).all()
    return [
        ScoreResponse(
            id=s.id,
            church_id=s.church_id,
            week_of=s.week_of,
            title=s.title,
            file_uri=s.file_uri,
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
        file_uri=score.file_uri,
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
        score.week_of = payload.week_of
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
        file_uri=score.file_uri,
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