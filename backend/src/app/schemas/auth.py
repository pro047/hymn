import re
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

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

# Raised through ValueError, so pydantic emits it as `Value error, <text>`.
# The client strips that prefix and shows the rest, so these must be Korean.
PASSWORD_CASE_MESSAGE = "영문 대문자와 소문자를 모두 포함해야 합니다."
AGREED_TERMS_MESSAGE = "약관 동의가 필요합니다."


class LoginRequest(BaseModel):
    email: EmailStr
    # Deliberately NOT PASSWORD_MAX_LENGTH. Accounts created before the 16-char
    # cap existed must still be able to sign in.
    password: str = Field(..., min_length=PASSWORD_MIN_LENGTH, max_length=128)


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    email: EmailStr
    password: str = Field(
        ..., min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH
    )
    church: str = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    church_address: str = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    phone: str = Field(..., min_length=PHONE_MIN_LENGTH, max_length=PHONE_MAX_LENGTH)
    agreed_terms: bool = Field(..., description="User agreed to terms")

    @field_validator("password")
    @classmethod
    def password_must_mix_case(cls, value: str) -> str:
        if not _HAS_LOWER.search(value) or not _HAS_UPPER.search(value):
            raise ValueError(PASSWORD_CASE_MESSAGE)
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
