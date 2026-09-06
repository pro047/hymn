import re
from datetime import date
from typing import Annotated

from fastapi import Path
from pydantic import BeforeValidator

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
