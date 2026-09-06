import re
from datetime import date
from typing import Annotated

from fastapi import Path
from pydantic import BaseModel, BeforeValidator, Field

ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def require_iso_date(value: object) -> object:
    """Rejects any string that is not exactly YYYY-MM-DD before pydantic's
    own (lax) date coercion sees it — a path parameter is always a str, so
    a non-str input here is left untouched to fall through to that coercion.
    """
    if isinstance(value, str) and not ISO_DATE_PATTERN.match(value):
        raise ValueError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
    return value


WeekOfPath = Annotated[date, BeforeValidator(require_iso_date), Path(description="YYYY-MM-DD")]


class ContiItemResponse(BaseModel):
    """One song's place in a week's conti.

    Deliberately not part of GET /scores: that response is a shared contract
    with hymn_app, which has no self-update path, so adding a key there could
    stop the church's tablets on a deploy. This is a web-only surface.
    """

    score_id: str
    title: str
    starts_new_page: bool


class ContiResponse(BaseModel):
    week_of: date
    items: list[ContiItemResponse]


class ContiOrderItemRequest(BaseModel):
    score_id: str
    starts_new_page: bool = False


class ContiOrderRequest(BaseModel):
    """The week's songs in the order they will be sung.

    Position comes from the list itself, not from a number the client sends:
    order_no is an implementation detail of how the server stores a sequence,
    and asking the client to compute it invites two sources of truth.
    """

    items: list[ContiOrderItemRequest] = Field(min_length=1)
