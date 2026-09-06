from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import ObjectReader, get_current_user, get_object_reader
from app.models import User
from app.schemas.conti import WeekOfPath
from app.services.conti import ContiEmpty, ContiFileNotAnImage, ContiFileUnreadable, build_week_conti_pdf

router = APIRouter()


@router.get(
    "/weeks/{week_of}/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_week_conti_pdf(
    week_of: WeekOfPath,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    read_object: ObjectReader = Depends(get_object_reader),
) -> Response:
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
