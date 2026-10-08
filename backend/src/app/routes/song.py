"""The library: every song of the caller's church.

Uploading files a song and nothing else; a Sunday gets a song only by placing
one from here. The songs table already held one row per church and title with
its canonical file, so the library is that table rather than a list kept
beside it.
"""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import ObjectProbe, get_object_probe, require_leader
from app.models import Score, Song, User
from app.schemas.song import (
    SongLibraryItem,
    SongUploadRequest,
    SongUploadResponse,
    SongUsageRequest,
    SongUsageResponse,
)
from app.services.song import (
    add_usage,
    get_or_reuse_song,
    has_usage_in_week,
    normalize_week_date,
    replace_song_file,
)
from app.utils.files import extension_from_input
from app.utils.s3 import object_url, presign_get, presign_put, presign_score_download

router = APIRouter(prefix="/songs", tags=["songs"])


def _church_song_or_404(session: Session, user: User, song_id: str) -> Song:
    song = session.get(Song, song_id)
    if not song or song.church_id != user.church_id:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


@router.get("", response_model=list[SongLibraryItem])
def list_songs(
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
):
    # "Used" means filed on a Sunday, however it got there. Usages without a
    # week are legacy library-upload drafts and never counted.
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
    rows = (
        session.query(Song, use_count, usage.c.last_week_of)
        .outerjoin(usage, usage.c.song_id == Song.id)
        .filter(Song.church_id == user.church_id)
        .order_by(desc(Song.created_at), Song.id)
        .all()
    )

    return [
        SongLibraryItem(
            song_id=song.id,
            title=song.title,
            file_url=song.file_url,
            file_uri=song.file_uri,
            download_url=presign_score_download(song.file_uri),
            created_at=song.created_at,
            last_week_of=last_week_of,
            use_count=count,
        )
        for song, count, last_week_of in rows
    ]


@router.post("", response_model=SongUploadResponse, status_code=status.HTTP_201_CREATED)
def upload_song(
    payload: SongUploadRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
    object_exists: ObjectProbe = Depends(get_object_probe),
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
    if not created:
        # The row is written before the browser PUTs the file, so an upload
        # that died on the way leaves a song whose file never arrived. Taking
        # the same title again is how that song gets its file; only keys this
        # route mints are probed, since legacy keys ("a.pdf") were never in the
        # bucket to begin with.
        if song.file_uri and song.file_uri.startswith(f"scores/{user.church_id}/") and not object_exists(song.file_uri):
            replace_song_file(session, song, file_url=object_url(key), file_uri=key)
        else:
            # Otherwise a same-titled upload is refused rather than reused: the
            # song is already in the library, and taking the new file silently
            # would either drop it or redraw every Sunday that used the old one.
            raise HTTPException(
                status_code=409,
                detail="이미 보관함에 있는 곡입니다. 보관함에서 골라 배치해 주세요.",
            )
    session.commit()

    return SongUploadResponse(
        song_id=song.id,
        upload_url=presign_put(key, 900),
        download_url=presign_get(key),
        s3_key=key,
    )


@router.post("/{song_id}/usages", response_model=SongUsageResponse)
def place_song(
    song_id: str,
    payload: SongUsageRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
):
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

    return SongUsageResponse(song_id=song.id, score_id=score.id)
