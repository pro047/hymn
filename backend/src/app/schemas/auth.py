import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, EmailStr, Field, field_validator

# SOURCE OF TRUTH for signup input rules.
# frontend/src/lib/validation/auth-schema.ts mirrors these; change both together.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 16
NAME_MAX_LENGTH = 255
PHONE_MIN_LENGTH = 8
PHONE_MAX_LENGTH = 32

# Split out of the old single `.{8,16}` rule so length stays a Field constraint
# (which yields a typed 422 the client can word itself) and case does not.
_HAS_LOWER = re.compile(r"[a-z]")
_HAS_UPPER = re.compile(r"[A-Z]")

# C0 controls plus DEL. CR and LF are the ones that actually bite: the HTML value
# sanitization algorithm removes them from <input type="password">, so a password
# containing one can be registered through the API but never typed back in on the
# web form — an account that can never sign in again.
_HAS_CONTROL_CHAR = re.compile(r"[\x00-\x1f\x7f]")

# Raised through ValueError, so pydantic emits it as `Value error, <text>`.
# The client strips that prefix and shows the rest, so these must be Korean.
PASSWORD_CASE_MESSAGE = "영문 대문자와 소문자를 모두 포함해야 합니다."
PASSWORD_CONTROL_MESSAGE = "비밀번호에 줄바꿈이나 탭 같은 제어 문자를 넣을 수 없습니다."
AGREED_TERMS_MESSAGE = "약관 동의가 필요합니다."


def _strip(value: object) -> object:
    """Trims a str, passes anything else through for pydantic to reject."""
    return value.strip() if isinstance(value, str) else value


def normalize_email(value: object) -> object:
    """Case- and whitespace-folds an address so lookups match what was stored."""
    return value.strip().lower() if isinstance(value, str) else value


# BeforeValidator runs ahead of the Field constraints (verified against pydantic
# 2.x), so min_length sees the trimmed value: "   " is rejected as
# string_too_short with ctx, which the client already words itself. Trimming
# afterwards instead would let it through and store an empty church name, and
# Church.name is unique — every such signup would then join one shared "" church.
TrimmedStr = Annotated[str, BeforeValidator(_strip)]
NormalizedEmail = Annotated[EmailStr, BeforeValidator(normalize_email)]


class LoginRequest(BaseModel):
    email: NormalizedEmail
    # Deliberately NOT PASSWORD_MAX_LENGTH, and deliberately not control-char
    # checked either. Both would lock out accounts that predate the rule; the
    # gate belongs on the way in, not on the way back.
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=128)


class SignupRequest(BaseModel):
    name: TrimmedStr = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    email: NormalizedEmail
    password: str = Field(
        ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
    church: TrimmedStr = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    church_address: TrimmedStr = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    phone: TrimmedStr = Field(..., min_length=PHONE_MIN_LENGTH, max_length=PHONE_MAX_LENGTH)
    agreed_terms: bool = Field(..., description="User agreed to terms")

    @field_validator("password")
    @classmethod
    def password_must_mix_case(cls, value: str) -> str:
        if not _HAS_LOWER.search(value) or not _HAS_UPPER.search(value):
            raise ValueError(PASSWORD_CASE_MESSAGE)
        return value

    @field_validator("password")
    @classmethod
    def password_must_be_typeable(cls, value: str) -> str:
        if _HAS_CONTROL_CHAR.search(value):
            raise ValueError(PASSWORD_CONTROL_MESSAGE)
        return value

    @field_validator("agreed_terms")
    @classmethod
    def terms_must_be_agreed(cls, value: bool) -> bool:
        if not value:
            raise ValueError(AGREED_TERMS_MESSAGE)
        return value


class EmailCheckResponse(BaseModel):
    available: bool


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=20, max_length=512)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class AuthUser(BaseModel):
    id: str
    church_id: str
    email: str
    name: str
    role: str


class AuthChurch(BaseModel):
    id: str
    name: str
    code: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(BaseModel):
    tokens: TokenPair
    user: AuthUser
    church: AuthChurch


class SignupResponse(LoginResponse):
    pass


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class SessionResponse(BaseModel):
    user: AuthUser
    church: AuthChurch
    issued_at: datetime
