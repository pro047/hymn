from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db import get_session
from app.deps import get_current_user, get_optional_user, require_leader
from app.models import Score, User
from app.schemas.score import (
    ScoreEditRequest,
    ScoreEditResponse,
    ScoreEditUploadResponse,
    ScoreFileUploadRequest,
    ScoreFileUploadResponse,
    ScoreResponse,
    ScoreUpdate,
)
from app.services.score_edit import clear_edit, save_edit
from app.services.song import (
    SongTitleTaken,
    attach_usage,
    normalize_week_date,
    rename_song,
    replace_song_file,
)
from app.utils.files import extension_from_input
from app.utils.s3 import object_url, presign_put, presign_score_download

router = APIRouter()


def _reject_foreign_object_key(file_uri: str, church_id: str) -> None:
    """Refuses a storage key that is not this church's, or returns.

    file_uri is written straight through from the request body on PATCH, and
    presign_score_download signs anything under the scores/ prefix. Together
    those made the route a signing oracle: point a score's file_uri at another
    church's key and the server hands back a presigned GET for it. That
    survives scoping the read routes, because the URL is minted on demand from
    a key rather than read off a row the caller may see — so it is closed here,
    on the way in.

    Checked only when a key is supplied, and only on write. Rows already stored
    are left alone: the keys predating the s3 branch ("a.pdf", "local/x.pdf")
    do not match the prefix and already resolve to download_url=None, and
    rejecting them here would make a title-only edit fail on an old score.
    """
    if not is_church_object_key(file_uri, church_id):
        raise HTTPException(400, "잘못된 파일 경로입니다.")


def is_church_object_key(file_uri: str, church_id: str) -> bool:
    """Whether a key has exactly the shape the server issues for this church:
    scores/{church_id}/{name}.

    Segments rather than a prefix: scores/{mine}/../{theirs}/x.png starts with
    this church's prefix too. Whether S3 would resolve that to the other
    church's object was never established, so the key is refused on its shape
    instead of on what the store might do with it.
    """
    parts = file_uri.split("/")
    if len(parts) != 3:
        return False
    root, owner, name = parts
    return root == "scores" and owner == church_id and name not in ("", ".", "..")


def _own_score_or_404(session: Session, score_id: str, user: User) -> Score:
    """A score of the caller's own church, or 404.

    404 rather than 403 for a score that exists in another church: 403 would
    confirm the id is real, which is one bit more than a caller outside that
    congregation should get. Same choice the library routes make.

    This is the church boundary only. Who inside the church may write is
    decided before the route body runs, by Depends(require_leader) on every
    route but the two reads.
    """
    score = session.get(Score, score_id)
    if score is None or score.church_id != user.church_id:
        raise HTTPException(404, "악보를 찾을 수 없습니다.")
    return score


@router.get("/scores", response_model=list[ScoreResponse])
def list_scores(
    session: Session = Depends(get_session),
    user: User | None = Depends(get_optional_user),
):
    query = session.query(Score).options(joinedload(Score.song)).filter(Score.week_of.is_not(None))
    # A signed-in caller sees their own church. Without a token the answer is
    # still every church's: the tablets cannot sign in yet, and closing that
    # waits on an app release (.claude/plan-community.md, M4).
    if user is not None:
        query = query.filter(Score.church_id == user.church_id)
    scores = query.order_by(Score.created_at.asc()).all()
    return [
        ScoreResponse(
            id=s.id,
            church_id=s.church_id,
            week_of=s.week_of,
            title=s.song.title,
            file_url=s.song.file_url,
            file_uri=s.song.file_uri,
            # This week's edit first, as conti reads it. The app draws this URL
            # and nothing else, so it is the only place an edit can reach it.
            # file_uri stays the song's: the web replaces the file through it.
            download_url=presign_score_download(s.edited_file_uri or s.song.file_uri),
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
    legacy weekless library uploads out of the public answer. This route had no filter and no dependency, so it handed
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
        download_url=presign_score_download(song.file_uri),
        created_at=score.created_at,
        song_id=score.song_id,
    )

@router.post("/scores/{score_id}/file", response_model=ScoreFileUploadResponse)
def create_score_file_upload(
    score_id: str,
    payload: ScoreFileUploadRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
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
    left in the bucket: nothing references it, and presign_score_download signs only the
    key stored on the row.

    Two paths leave an object nothing points at, and neither is cleaned up here.
    A PATCH that fails after a successful upload orphans the new key, and a
    retry signs another one rather than reusing it. Both are bounded by how
    often a write fails and cost a few KB each; a sweep over keys absent from
    the scores table is the way to reclaim them if it ever matters.
    """
    score = _own_score_or_404(session, score_id, user)
    ext = extension_from_input(payload.filename, payload.content_type)
    key = f"scores/{score.church_id}/{uuid4()}.{ext}"
    return {"upload_url": presign_put(key, 900), "s3_key": key}


def _edit_state_of(score: Score) -> ScoreEditResponse:
    """This week's edit, and the sheet to lay it over.

    The source is the one the edit was drawn against, falling back to the
    song's own file for a week that has never been edited — and for every row
    that predates the column. Handing back the song's current file instead
    would replay saved markings onto a sheet they were never placed on, as
    soon as any other week replaced it: the conti keeps drawing the flattened
    picture correctly, so nothing looks wrong until this screen opens.

    Signed on every read rather than stored: a presigned URL expires, and one
    written into a row outlives its own credential.
    """
    return ScoreEditResponse(
        edited_file_uri=score.edited_file_uri,
        edit_doc=score.edit_doc,
        source_image_url=presign_score_download(score.edit_source_uri or score.song.file_uri),
    )


@router.get("/scores/{score_id}/edit", response_model=ScoreEditResponse)
def get_score_edit(
    score_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
):
    """What the editor needs to open this week's sheet.

    Leader-only like the save it leads to: this is the read the edit screen
    opens with, and a member who could load it only to be refused on save
    would have drawn for nothing.

    source_image_url is the song's file, not the edited one. The document is
    replayed over it, so the edited sheet would put every earlier marking on
    the canvas twice — once painted into the background, once as the object
    that painted it.
    """
    score = _own_score_or_404(session, score_id, user)
    return _edit_state_of(score)


@router.post("/scores/{score_id}/edited-file", response_model=ScoreEditUploadResponse)
def create_score_edit_upload(
    score_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
):
    """A presigned PUT for the flattened sheet the editor is about to produce.

    The same three-step shape as replacing a score's file (sign, upload, then
    write the key): an upload that fails leaves the week showing the sheet it
    already had.

    The key is minted here rather than accepted from the request, which is what
    keeps this from becoming a signing oracle — the caller never gets to name
    an object. PUT /scores/{id}/edit checks the key it is handed anyway, since
    that route cannot tell a key this one minted from one the caller invented.

    Always .png: the editor flattens a canvas, and a canvas has transparent
    pixels wherever nothing was drawn. JPEG would fill those with black.
    """
    score = _own_score_or_404(session, score_id, user)
    key = f"scores/{score.church_id}/{uuid4()}.png"
    return {"upload_url": presign_put(key, 900), "s3_key": key}


@router.put("/scores/{score_id}/edit", response_model=ScoreEditResponse)
def save_score_edit(
    score_id: str,
    payload: ScoreEditRequest,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
):
    """Records a finished edit against this one week.

    PUT, not PATCH: the request carries the whole edit, and applying half of
    one is not a thing the editor can ask for.

    The key goes through the same gate every other written key does. Without
    it, a caller could name another church's object here and have the server
    hand back signed GETs for it through conti — the read side signs anything
    under scores/, for reasons documented in build_week_conti_pdf.
    """
    score = _own_score_or_404(session, score_id, user)
    _reject_foreign_object_key(payload.edited_file_uri, score.church_id)
    save_edit(
        score,
        edited_file_uri=payload.edited_file_uri,
        edit_doc=payload.edit_doc,
        # The song's file as it stands now, which is the sheet the editor was
        # handed when it opened. Reading it here rather than trusting the
        # request keeps the record honest with no second source to reconcile.
        source_file_uri=score.song.file_uri,
    )
    session.commit()
    session.refresh(score)
    return _edit_state_of(score)


@router.delete("/scores/{score_id}/edit", response_model=ScoreEditResponse)
def delete_score_edit(
    score_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
):
    """Takes this week back to the song's own sheet.

    The only way back to unedited: saving an empty canvas would still flatten
    to a picture, and the week would go on showing that copy rather than the
    song's file as it changes.

    200 with the cleared state rather than 204, and clearing an unedited score
    is not an error — the screen wants the same body either way, and a leader
    pressing "원본으로" twice has not done anything wrong.
    """
    score = _own_score_or_404(session, score_id, user)
    clear_edit(score)
    session.commit()
    session.refresh(score)
    return _edit_state_of(score)


@router.patch("/scores/{score_id}", response_model=ScoreResponse)
def update_score(
    score_id: str,
    payload: ScoreUpdate,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
):
    score = _own_score_or_404(session, score_id, user)
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
        normalized_week_of = normalize_week_date(payload.week_of)
        if normalized_week_of != score.week_of:
            attach_usage(session, score, normalized_week_of)
    if payload.file_uri is not None:
        _reject_foreign_object_key(payload.file_uri, score.church_id)
        # object_url, not the key itself — the column holds a URL everywhere
        # else (the library upload does the same) and every client
        # reads it as `download_url ?? file_url`. Storing the bare key survives
        # only because the gate above forces the scores/ prefix, which is
        # exactly what makes presign_score_download sign it and hide the fallback.
        file_url = object_url(payload.file_uri)
        replace_song_file(session, song, file_url=file_url, file_uri=payload.file_uri)
        score.file_url = file_url
        score.file_uri = payload.file_uri
        # An edit was drawn on the sheet being replaced, so it cannot survive
        # the replacement: conti reads coalesce(edited_file_uri, song file),
        # and leaving it set would keep drawing the old sheet while the upload
        # looked like it had done nothing. Only this usage's edit is dropped —
        # other weeks' edits are their own finished sheets, and this route was
        # never asked about them.
        clear_edit(score)

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
        download_url=presign_score_download(song.file_uri),
        created_at=score.created_at,
        song_id=score.song_id,
    )

@router.delete('/scores/{score_id}', status_code=204)
def delete_score(
    score_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(require_leader),
):
    score = _own_score_or_404(session, score_id, user)
    session.delete(score)
    session.commit()
    return
