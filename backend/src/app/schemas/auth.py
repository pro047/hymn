import re
from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

# SOURCE OF TRUTH for signup input rules.
# frontend/src/lib/validation/auth-schema.ts mirrors these; change both together.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 16
NAME_MAX_LENGTH = 255
PHONE_MIN_LENGTH = 8
PHONE_MAX_LENGTH = 32
# Matches the churches.join_code column, not the 8 the generator emits: the
# column is deliberately wider so the format can grow, and a request carrying an
# older or longer code should reach the comparison rather than be rejected here.
JOIN_CODE_MAX_LENGTH = 16

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
PASSWORD_UNCHANGED_MESSAGE = "새 비밀번호가 현재 비밀번호와 같습니다."
AGREED_TERMS_MESSAGE = "약관 동의가 필요합니다."


def _strip(value: object) -> object:
    """Trims a str, passes anything else through for pydantic to reject."""
    return value.strip() if isinstance(value, str) else value


def validate_password_strength(value: str) -> str:
    """Every rule a password has to clear on its way in, in one place.

    Signup and a password change share it deliberately. Two gates for the same
    thing drift — password_confirm and church_is_registered both did — and the
    drift here would be silent: an account could set a password its own signup
    form would have refused.
    """
    if not _HAS_LOWER.search(value) or not _HAS_UPPER.search(value):
        raise ValueError(PASSWORD_CASE_MESSAGE)
    if _HAS_CONTROL_CHAR.search(value):
        raise ValueError(PASSWORD_CONTROL_MESSAGE)
    return value


def normalize_email(value: object) -> object:
    """Case- and whitespace-folds an address so lookups match what was stored."""
    return value.strip().lower() if isinstance(value, str) else value


def normalize_join_code(value: object) -> object:
    """Folds case and whitespace on an invite code before it is compared.

    The generated alphabet is lowercase by construction, so folding can never
    make two distinct codes collide. It is here because the code travels by
    hand: a phone keyboard capitalising the first letter, or a space picked up
    while copying, would otherwise read as the wrong code and cost a 403.
    """
    return value.strip().lower() if isinstance(value, str) else value


# BeforeValidator runs ahead of the Field constraints (verified against pydantic
# 2.x), so min_length sees the trimmed value: "   " is rejected as
# string_too_short with ctx, which the client already words itself. Trimming
# afterwards instead would let it through and store an empty church name, and
# Church.name is unique — every such signup would then join one shared "" church.
TrimmedStr = Annotated[str, BeforeValidator(_strip)]
NormalizedEmail = Annotated[EmailStr, BeforeValidator(normalize_email)]
JoinCode = Annotated[str, BeforeValidator(normalize_join_code)]
# A password being *set*, as opposed to one being offered as proof of identity.
# Length stays a Field constraint and only the rest moves into the validator:
# pydantic reports a constraint as string_too_short/string_too_long with ctx,
# which the client reads to word its own message, while anything raised inside
# AfterValidator arrives as value_error carrying only the sentence above. Core
# validation runs first and skips the AfterValidator when it fails, so a short
# password is reported as short rather than as a case violation.
NewPassword = Annotated[
    str,
    Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH),
    AfterValidator(validate_password_strength),
]
# A password being *checked*. Deliberately NOT PASSWORD_MAX_LENGTH and
# deliberately not strength-checked: rules on this side lock out accounts that
# predate the rule. The gate belongs on the way in, not on the way back.
CurrentPassword = Annotated[str, Field(min_length=PASSWORD_MIN_LENGTH, max_length=128)]
# The church name arrives as a query string on /auth/check-church, where nothing
# else bounds its length. Trimmed the same way SignupRequest.church is, so the
# lookup asks about the row a signup with that name would actually reach.
ChurchNameQuery = Annotated[TrimmedStr, Field(min_length=1, max_length=NAME_MAX_LENGTH)]


class LoginRequest(BaseModel):
    email: NormalizedEmail
    password: CurrentPassword


class SignupRequest(BaseModel):
    name: TrimmedStr = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    email: NormalizedEmail
    password: NewPassword
    church: TrimmedStr = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    # Optional in the schema, required by the service — but only for a church
    # that already exists. Founding one issues the code instead of asking for
    # it, and a required field would make that signup impossible to word.
    join_code: JoinCode | None = Field(default=None, max_length=JOIN_CODE_MAX_LENGTH)
    church_address: TrimmedStr = Field(..., min_length=1, max_length=NAME_MAX_LENGTH)
    phone: TrimmedStr = Field(..., min_length=PHONE_MIN_LENGTH, max_length=PHONE_MAX_LENGTH)
    agreed_terms: bool = Field(..., description="User agreed to terms")

    @field_validator("agreed_terms")
    @classmethod
    def terms_must_be_agreed(cls, value: bool) -> bool:
        if not value:
            raise ValueError(AGREED_TERMS_MESSAGE)
        return value


class PasswordChangeRequest(BaseModel):
    current_password: CurrentPassword
    new_password: NewPassword

    @model_validator(mode="after")
    def new_password_must_differ(self) -> "PasswordChangeRequest":
        """Refuses a change that changes nothing.

        Cross-field, so it cannot be a field_validator. The cost is where the
        message lands: pydantic reports it against the model rather than a
        field, so the client shows it as a form-level alert instead of under
        the new-password box. The zod schema repeats the rule on the field so
        the usual case never reaches here.
        """
        if self.new_password == self.current_password:
            raise ValueError(PASSWORD_UNCHANGED_MESSAGE)
        return self


class EmailCheckResponse(BaseModel):
    available: bool


class CheckChurchResponse(BaseModel):
    """Whether that name is taken, and deliberately nothing else.

    The form needs to know which of the two signup shapes to render — ask for
    an invite code, or say you are about to found a church. Returning the code
    alongside would hand it to any unauthenticated caller who guessed the name,
    which is the exact gate this milestone exists to close.
    """

    exists: bool


class JoinCodeResponse(BaseModel):
    code: str


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
    # None for a member. The code lets anyone who holds it join the church, so
    # only the account that can rotate it is shown it — a member's browser
    # storage, or any log of their session response, is not a place for it.
    code: str | None


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
