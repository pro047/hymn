from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["leader", "member"]

class AuthLogin(BaseModel):
    church_code: str = Field(..., min_length=2, max_length=32)
