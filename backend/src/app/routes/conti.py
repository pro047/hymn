from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import ObjectReader, get_current_user, get_object_reader
from app.models import User
from app.rate_limit import CONTI_ORDER_LIMIT, CONTI_PDF_LIMIT, CONTI_READ_LIMIT, limiter
from app.schemas.conti import ContiOrderRequest, ContiResponse, WeekOfPath
from app.services.conti import (
    ContiEmpty,
    ContiFileNotAnImage,
    ContiFileUnreadable,
    ContiOrderItem,
    ContiOrderMismatch,
    build_week_conti_pdf,
    list_week_pages,
    set_week_order,
)
from app.services.conti_pdf import slot_ratio
from app.services.song import normalize_week_date
from app.utils.s3 import presign_score_download

router = APIRouter()


@router.get(
    "/weeks/{week_of}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
@limiter.limit(CONTI_PDF_LIMIT)
def get_week_conti_pdf(
    request: Request,
    week_of: WeekOfPath,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    read_object: ObjectReader = Depends(get_object_reader),
) -> Response:
    # Every write path files a Score under the week's Sunday
    # (routes/score.py, routes/saved_score.py), so a raw weekday here would
    # ask about a week that cannot exist in the table: a 404 that looks like
    # "nothing filed" when the songs are right there under Sunday's date.
    week_of = normalize_week_date(week_of)
    try:
        pdf_bytes = build_week_conti_pdf(
            session, church_id=user.church_id, week_of=week_of, read_object=read_object
        )
    except ContiEmpty:
        raise HTTPException(404, "그 주차에 등록된 곡이 없습니다.") from None
    except ContiFileNotAnImage as exc:
        raise HTTPException(
            409, f"이미지가 아닌 악보 파일이 있어 콘티를 만들 수 없습니다: {exc.title}"
        ) from None
    except ContiFileUnreadable as exc:
        raise HTTPException(502, f"악보 파일을 불러오지 못했습니다: {exc.title}") from None

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="conti-{week_of.isoformat()}.pdf"'},
    )


@router.get("/weeks/{week_of}/conti", response_model=ContiResponse)
@limiter.limit(CONTI_READ_LIMIT)
def get_week_conti(
    request: Request,
    week_of: WeekOfPath,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ContiResponse:
    """This week's songs in running order, for the conti editing screen.

    An empty week is 200 with no items, not the 404 the PDF route returns:
    the screen has to render "nothing filed yet" and a leader opening a week
    early has not made an error.
    """
    week_of = normalize_week_date(week_of)
    pages = list_week_pages(session, church_id=user.church_id, week_of=week_of)
    return ContiResponse(
        week_of=week_of,
        slot_ratio=slot_ratio(),
        pages=[
            [
                {
                    "score_id": entry.score_id,
                    "title": entry.title,
                    "starts_new_page": entry.starts_new_page,
                    # Signed here rather than handed the raw key: the browser
                    # draws the real sheet in the preview, and the bucket is
                    # not public. Same guard as every other read path — a key
                    # this app did not mint answers None, so the screen says
                    # "no file" instead of drawing a broken image and offering
                    # a PDF button that can only 502.
                    "image_url": presign_score_download(entry.file_uri),
                }
                for entry in page
            ]
            for page in pages
        ],
    )


@router.patch("/weeks/{week_of}/conti/order", response_model=ContiResponse)
@limiter.limit(CONTI_ORDER_LIMIT)
def patch_week_conti_order(
    request: Request,
    week_of: WeekOfPath,
    payload: ContiOrderRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ContiResponse:
    week_of = normalize_week_date(week_of)
    try:
        set_week_order(
            session,
            church_id=user.church_id,
            week_of=week_of,
            items=[
                ContiOrderItem(score_id=item.score_id, starts_new_page=item.starts_new_page)
                for item in payload.items
            ],
        )
    except ContiOrderMismatch:
        raise HTTPException(400, "그 주차의 곡 전체를 한 번씩 보내야 합니다.") from None
    session.commit()
    return get_week_conti(request, week_of, session=session, user=user)
