from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func
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
from app.services.song import (
    add_usage,
    get_or_reuse_song,
    has_usage_in_week,
    normalize_week_date,
)
from app.utils.files import extension_from_input
from app.utils.s3 import object_url, presign_get, presign_put, presign_score_download

router = APIRouter(prefix="/me/saved-scores", tags=["saved-scores"])




def _get_saved_song(session: Session, user_id: str, song_id: str) -> SavedScore | None:
    return (
        session.query(SavedScore)
        .filter(SavedScore.user_id == user_id, SavedScore.song_id == song_id)
        .first()
    )


def _church_song_or_404(session: Session, user: User, song_id: str) -> Song:
    song = session.get(Song, song_id)
    if not song or song.church_id != user.church_id:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


@router.get("", response_model=list[SavedScoreItem])
def list_saved_scores(
    sort: Literal["recent", "frequent"] = Query(default="recent"),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    # "Used" means filed on a Sunday, however it got there -- an upload or an
    # apply -- so both figures come off the song's usages rather than a counter
    # that only the library's own apply ever bumped.
    usage = (
        session.query(
            Score.song_id.label("song_id"),
            func.count(Score.id).label("use_count"),
            func.max(Score.week_of).label("last_week_of"),
        )
        .filter(Score.church_id == user.church_id, Score.week_of.is_not(None))
        .group_by(Score.song_id)
        .subquery()
    )
    use_count = func.coalesce(usage.c.use_count, 0)
    query = (
        session.query(SavedScore, Song, use_count, usage.c.last_week_of)
        .join(Song, Song.id == SavedScore.song_id)
        .outerjoin(usage, usage.c.song_id == Song.id)
        .filter(SavedScore.user_id == user.id)
    )

    if sort == "frequent":
        query = query.order_by(
            desc(use_count),
            usage.c.last_week_of.desc().nulls_last(),
            desc(SavedScore.created_at),
        )
    else:
        query = query.order_by(desc(SavedScore.created_at))

    return [
        SavedScoreItem(
            song_id=song.id,
            title=song.title,
            file_url=song.file_url,
            file_uri=song.file_uri,
            download_url=presign_score_download(song.file_uri),
            saved_at=saved.created_at,
            last_week_of=last_week_of,
            use_count=count,
        )
        for saved, song, count, last_week_of in query.all()
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

    # A song and an entry, no Sunday: it is filed on one when it is applied.
    session.add(SavedScore(user_id=user.id, song_id=song.id))
    session.commit()

    return SavedScoreUploadResponse(
        song_id=song.id,
        upload_url=presign_put(key, 900),
        download_url=presign_get(key),
        s3_key=key,
    )


@router.post("/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
def save_score(
    song_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    _church_song_or_404(session, user, song_id)
    if _get_saved_song(session, user.id, song_id):
        return

    session.add(SavedScore(user_id=user.id, song_id=song_id))
    session.commit()
    return


@router.delete("/{song_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_saved_score(
    song_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    saved = _get_saved_song(session, user.id, song_id)
    if not saved:
        return

    session.delete(saved)
    session.commit()
    return


@router.post("/{song_id}/apply", response_model=SavedScoreUseResponse)
def apply_saved_score(
    song_id: str,
    payload: SavedScoreApplyRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if not _get_saved_song(session, user.id, song_id):
        raise HTTPException(status_code=404, detail="Saved score not found")
    song = _church_song_or_404(session, user, song_id)

    # One song, many Sundays: a new usage is filed and the Sundays the song is
    # already on keep it.
    week_of = normalize_week_date(payload.week_of)
    if has_usage_in_week(session, song_id=song.id, week_of=week_of):
        raise HTTPException(status_code=409, detail="이 곡은 이미 그 주차에 등록되어 있습니다.")
    score = add_usage(
        session,
        song,
        church_id=user.church_id,
        uploader_id=user.id,
        week_of=week_of,
    )
    session.commit()

    return SavedScoreUseResponse(song_id=song.id, score_id=score.id)
