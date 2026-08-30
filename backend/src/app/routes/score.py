from datetime import timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db import get_session
from app.deps import get_current_user
from app.models import Score, User
from app.schemas.score import (
    ScoreCreate,
    ScoreCreateResponse,
    ScoreFileUploadRequest,
    ScoreFileUploadResponse,
    ScoreResponse,
    ScoreUpdate,
)
from app.services.song import (
    SongTitleTaken,
    attach_usage,
    get_or_reuse_song,
    has_usage_in_week,
    rename_song,
    replace_song_file,
)
from app.utils.files import extension_from_input
from app.utils.s3 import object_url, presign_get, presign_put

router = APIRouter()

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


def _reject_foreign_object_key(file_uri: str, church_id: str) -> None:
    """Refuses a storage key that is not this church's, or returns.

    file_uri is written straight through from the request body on the `local`
    branch, and _download_url signs anything under the scores/ prefix. Together
    those made the route a signing oracle: file a score whose file_uri is
    another church's key and the server hands back a presigned GET for it. That
    survives scoping the read routes, because the URL is minted on demand from
    a key rather than read off a row the caller may see — so it is closed here,
    on the way in.

    Checked only when a key is supplied, and only on write. Rows already stored
    are left alone: the keys predating the s3 branch ("a.pdf", "local/x.pdf")
    do not match the prefix and already resolve to download_url=None, and
    rejecting them here would make a title-only edit fail on an old score.
    """
    if not file_uri.startswith(f"scores/{church_id}/"):
        raise HTTPException(400, "잘못된 파일 경로입니다.")


def _own_score_or_404(session: Session, score_id: str, user: User) -> Score:
    """A score of the caller's own church, or 404.

    404 rather than 403 for a score that exists in another church: 403 would
    confirm the id is real, which is one bit more than a caller outside that
    congregation should get. Same choice the saved-scores routes make.
    """
    score = session.get(Score, score_id)
    if score is None or score.church_id != user.church_id:
        raise HTTPException(404, "악보를 찾을 수 없습니다.")
    return score


def _writable_score_or_error(session: Session, score_id: str, user: User) -> Score:
    """A score the caller may modify: their own upload, or any of the church's
    if they lead it.

    403 rather than 404 inside the church, unlike the cross-church case above:
    a member can already read the score, so its existence is not the secret —
    only the write is refused. Rows predating uploader_id are NULL and so fall
    to the leader, which matches production: every legacy row was uploaded by
    the one account that exists, and that account leads its church.
    """
    score = _own_score_or_404(session, score_id, user)
    if user.role != "leader" and score.uploader_id != user.id:
        raise HTTPException(403, "본인이 올린 악보만 수정하거나 삭제할 수 있습니다.")
    return score

@router.post('/scores', response_model=ScoreCreateResponse)
def create_score(
    payload: ScoreCreate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    normalized_week_of = _normalize_week_date(payload.week_of)
    # From the token, never the body. The old route took church_id or a free
    # text church_name and created the church if the name was unknown, with no
    # authentication at all: anyone could file scores under any congregation.
    church_id = user.church_id

    if payload.storage_type == 's3':
        if not payload.filename:
            raise HTTPException(400, 'filename required for s3')
        ext = extension_from_input(payload.filename, payload.content_type)
        candidate_key = f"scores/{church_id}/{uuid4()}.{ext}"
        candidate_file_url = object_url(candidate_key)
        candidate_file_uri = candidate_key
    else:
        if not payload.file_uri:
            raise HTTPException(400, 'file_uri required for local')
        _reject_foreign_object_key(payload.file_uri, church_id)
        candidate_file_url = payload.file_uri
        candidate_file_uri = payload.file_uri

    song, created = get_or_reuse_song(
        session,
        church_id=church_id,
        title=payload.title,
        uploader_id=user.id,
        file_url=candidate_file_url,
        file_uri=candidate_file_uri,
    )
    if not created and has_usage_in_week(session, song_id=song.id, week_of=normalized_week_of):
        raise HTTPException(409, "이 곡은 이미 그 주차에 등록되어 있습니다.")

    # A reused song keeps its existing file; the candidate key above was never
    # uploaded to, so writing it into the usage snapshot would point at an
    # object that does not exist.
    file_url = candidate_file_url if created else song.file_url
    file_uri = candidate_file_uri if created else song.file_uri

    score = Score(
        church_id=church_id,
        uploader_id=user.id,
        song_id=song.id,
        title=payload.title,
        week_of=normalized_week_of,
        file_url=file_url,
        file_uri=file_uri,
        status='draft',
    )
    session.add(score)
    session.flush()
    attach_usage(session, score, normalized_week_of)
    session.commit()
    session.refresh(score)

    if payload.storage_type == 's3':
        return {
            "score_id": score.id,
            "upload_url": presign_put(candidate_file_uri, 900) if created else None,
            "download_url": _download_url(file_uri),
            "s3_key": file_uri,
            "reused_song": not created,
        }

    return {
        "score_id": score.id,
        "church_id": score.church_id,
        "week_of": score.week_of,
        "title": score.title,
        "file_uri": score.file_uri,
        "created_at": score.created_at,
        "reused_song": not created,
    }

@router.get("/scores", response_model=list[ScoreResponse])
def list_scores(session: Session = Depends(get_session)):
    scores = (
        session.query(Score)
        .options(joinedload(Score.song))
        .filter(Score.week_of.is_not(None))
        .order_by(Score.created_at.asc())
        .all()
    )
    return [
        ScoreResponse(
            id=s.id,
            church_id=s.church_id,
            week_of=s.week_of,
            title=s.song.title,
            file_url=s.song.file_url,
            file_uri=s.song.file_uri,
            download_url=_download_url(s.song.file_uri),
            created_at=s.created_at,
            song_id=s.song_id,
        )
        for s in scores
    ]

@router.get("/scores/{score_id}", response_model=ScoreResponse)
def get_score(
    score_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """One score of the caller's own church.

    Authenticated even though the list above is not, and the difference is not
    an oversight. list_scores filters on week_of IS NOT NULL, which keeps the
    saved-score uploads — the ones the UI calls a personal library — out of the
    public answer. This route had no filter and no dependency, so it handed
    those to anyone who could name the id.

    No client ever called it: the Flutter app makes exactly one request, GET
    /scores (hymn_app/lib/data/scores_api.dart:12), and the web uses this path
    for PATCH and DELETE only. Closing it therefore breaks nothing. It is kept
    rather than deleted so the next reader copies a protected route.
    """
    score = _own_score_or_404(session, score_id, user)
    song = score.song
    return ScoreResponse(
        id=score.id,
        church_id=score.church_id,
        week_of=score.week_of,
        title=song.title,
        file_url=song.file_url,
        file_uri=song.file_uri,
        download_url=_download_url(song.file_uri),
        created_at=score.created_at,
        song_id=score.song_id,
    )

@router.post("/scores/{score_id}/file", response_model=ScoreFileUploadResponse)
def create_score_file_upload(
    score_id: str,
    payload: ScoreFileUploadRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """A presigned PUT for replacing the file of a score that already exists.

    Mints a key and signs it, and touches no column. The client uploads to the
    URL and only then PATCHes file_uri, so an upload that fails leaves the score
    pointing at the file it already had rather than at an object that was never
    written. Doing it the other way round would show a broken image instead.

    The key is a fresh uuid rather than the score's current one. Overwriting in
    place would keep the old extension when the type changes, let any cache
    keyed on the unchanged URL keep serving the old image, and destroy the
    original before the new bytes are known to be good. The superseded object is
    left in the bucket: nothing references it, and _download_url signs only the
    key stored on the row.

    Two paths leave an object nothing points at, and neither is cleaned up here.
    A PATCH that fails after a successful upload orphans the new key, and a
    retry signs another one rather than reusing it. Both are bounded by how
    often a write fails and cost a few KB each; a sweep over keys absent from
    the scores table is the way to reclaim them if it ever matters.
    """
    score = _writable_score_or_error(session, score_id, user)
    ext = extension_from_input(payload.filename, payload.content_type)
    key = f"scores/{score.church_id}/{uuid4()}.{ext}"
    return {"upload_url": presign_put(key, 900), "s3_key": key}


@router.patch("/scores/{score_id}", response_model=ScoreResponse)
def update_score(
    score_id: str,
    payload: ScoreUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    score = _writable_score_or_error(session, score_id, user)
    song = score.song

    if payload.title is not None:
        try:
            rename_song(session, song, payload.title)
        except SongTitleTaken:
            raise HTTPException(409, "같은 제목의 곡이 이미 있습니다.") from None
        # Keeps this usage's own snapshot in step with the rename it asked
        # for; other weeks' snapshots are untouched, same as the file case.
        score.title = song.title
    if payload.week_of is not None:
        normalized_week_of = _normalize_week_date(payload.week_of)
        if normalized_week_of != score.week_of:
            attach_usage(session, score, normalized_week_of)
    if payload.file_uri is not None:
        # Both ways in get the same gate. Checking only on create would let the
        # caller file a harmless score and then point it at a foreign key.
        _reject_foreign_object_key(payload.file_uri, score.church_id)
        # object_url, not the key itself — the column holds a URL everywhere
        # else (create_score does the same at the s3 branch) and every client
        # reads it as `download_url ?? file_url`. Storing the bare key survives
        # only because the gate above forces the scores/ prefix, which is
        # exactly what makes _download_url sign it and hide the fallback.
        file_url = object_url(payload.file_uri)
        replace_song_file(session, song, file_url=file_url, file_uri=payload.file_uri)
        score.file_url = file_url
        score.file_uri = payload.file_uri

    session.commit()
    session.refresh(score)
    session.refresh(song)

    return ScoreResponse(
        id=score.id,
        church_id=score.church_id,
        week_of=score.week_of,
        title=song.title,
        file_url=song.file_url,
        file_uri=song.file_uri,
        download_url=_download_url(song.file_uri),
        created_at=score.created_at,
        song_id=score.song_id,
    )

@router.delete('/scores/{score_id}', status_code=204)
def delete_score(
    score_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
):
    score = _writable_score_or_error(session, score_id, user)
    session.delete(score)
    session.commit()
    return
