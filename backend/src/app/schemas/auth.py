from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class SignupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    church: str = Field(..., min_length=1, max_length=255)
    church_address: str = Field(..., min_length=1, max_length=255)
    phone: str = Field(..., min_length=8, max_length=32)
    agreed_terms: bool = Field(..., description="User agreed to terms")


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
