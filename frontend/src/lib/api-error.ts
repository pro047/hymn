// FastAPI puts two different shapes under the same `detail` key:
//   - HTTPException(status, detail="…")  -> a string
//   - Pydantic request validation (422)  -> an array of validation items
// Rendering `detail` directly turns the 422 case into "[object Object]", so
// every error response is funnelled through normalizeApiError() first.

export type ApiError = {
  status: number;
  /** Shown once above the form. Empty when every problem is field-scoped. */
  formError: string;
  /** Keyed by the backend field name (snake_case, as it appears in `loc`). */
  fieldErrors: Record<string, string>;
};

type ValidationItem = {
  type?: unknown;
  loc?: unknown;
  msg?: unknown;
  ctx?: Record<string, unknown>;
};

// Used when a validation error points at a field the form does not render, so
// the message promoted to the alert still says what it is about.
const FIELD_LABELS: Record<string, string> = {
  name: "이름",
  email: "이메일",
  password: "비밀번호",
  church: "교회",
  church_address: "교회주소",
  phone: "휴대폰 번호",
  agreed_terms: "약관 동의",
};

// Pydantic prefixes `loc` with where the value came from; the field name is
// whatever follows that prefix.
const LOC_PREFIXES = new Set(["body", "query", "path", "header", "cookie"]);

const GENERIC_FIELD_MESSAGE = "입력값이 올바르지 않습니다.";

function fieldNameOf(loc: unknown): string | null {
  if (!Array.isArray(loc)) return null;
  // Walk from the end so nested locs like ["body", "items", 0, "email"] resolve
  // to the leaf field rather than the container.
  for (let index = loc.length - 1; index >= 0; index -= 1) {
    const part: unknown = loc[index];
    if (typeof part === "string" && !LOC_PREFIXES.has(part)) return part;
  }
  return null;
}

// pydantic prefixes messages raised by @field_validator with this.
const VALUE_ERROR_PREFIX = /^Value error, /;
// EmailStr's wording. Matching on the message rather than on the field name
// keeps future email validators from being rewritten to the generic sentence.
const INVALID_EMAIL_MSG = "value is not a valid email address";

function messageOf(item: ValidationItem): string {
  const ctx = item.ctx ?? {};
  const msg = typeof item.msg === "string" ? item.msg : "";

  switch (item.type) {
    case "missing":
    case "string_type":
    case "bool_type":
      return "필수 입력 항목입니다.";
    case "string_too_short":
      // A ctx-less item would otherwise render the literal text "undefined";
      // break instead so the server's own wording is used.
      if (typeof ctx.min_length === "number") {
        return `최소 ${ctx.min_length}자 이상 입력해 주세요.`;
      }
      break;
    case "string_too_long":
      if (typeof ctx.max_length === "number") {
        return `최대 ${ctx.max_length}자까지 입력할 수 있습니다.`;
      }
      break;
    case "bool_parsing":
      return "동의 여부가 올바르지 않습니다.";
    case "value_error":
      if (msg.startsWith(INVALID_EMAIL_MSG)) return "올바른 이메일 주소를 입력해 주세요.";
      break;
    default:
      break;
  }
  // Fall back to the server's own wording rather than swallowing the reason.
  return msg ? msg.replace(VALUE_ERROR_PREFIX, "") : GENERIC_FIELD_MESSAGE;
}

function fromValidationItems(
  items: unknown[],
  status: number,
  fallback: string,
  renderedFields: readonly string[] | undefined
): ApiError {
  const fieldErrors: Record<string, string> = {};
  const formLines: string[] = [];

  for (const raw of items) {
    if (typeof raw !== "object" || raw === null) continue;
    const item = raw as ValidationItem;
    const field = fieldNameOf(item.loc);
    const message = messageOf(item);

    // A field the caller cannot render would be invisible inline, so promote it
    // to the alert with its label attached.
    if (field === null) {
      formLines.push(message);
      continue;
    }
    if (renderedFields && !renderedFields.includes(field)) {
      formLines.push(`${labelOf(field)}: ${message}`);
      continue;
    }
    // First error per field wins; later ones would just overwrite the message
    // the user is already looking at.
    if (!(field in fieldErrors)) fieldErrors[field] = message;
  }

  if (formLines.length === 0 && Object.keys(fieldErrors).length === 0) {
    return { status, formError: fallback, fieldErrors };
  }

  // `formError` holds only what the server actually said. The "check your
  // input" summary is derived at render time by alertMessageOf(), so it can
  // never outlive the field errors it summarises.
  return { status, formError: formLines.join(" "), fieldErrors };
}

/**
 * @param renderedFields field names the caller shows inline. Errors on any other
 *   field are promoted to `formError` instead of being silently dropped.
 */
export function normalizeApiError(
  payload: unknown,
  status: number,
  fallback: string,
  renderedFields?: readonly string[]
): ApiError {
  const detail =
    typeof payload === "object" && payload !== null
      ? (payload as { detail?: unknown }).detail
      : undefined;

  if (typeof detail === "string" && detail.trim()) {
    return { status, formError: detail, fieldErrors: {} };
  }
  if (Array.isArray(detail)) {
    return fromValidationItems(detail, status, fallback, renderedFields);
  }
  return { status, formError: fallback, fieldErrors: {} };
}

/** Reads an error response body defensively — a proxy may return HTML, not JSON. */
export async function readApiError(
  response: Response,
  fallback: string,
  renderedFields?: readonly string[]
): Promise<ApiError> {
  const payload: unknown = await response.json().catch(() => null);
  return normalizeApiError(payload, response.status, fallback, renderedFields);
}

/** For failures that never reached the server (network down, malformed body). */
export function toFormError(message: string): ApiError {
  return { status: 0, formError: message, fieldErrors: {} };
}

/**
 * What the alert should say, or "" to hide it. A 409/401 carries its own
 * sentence; a 422 whose problems are all inline still needs the alert to say
 * that something failed, otherwise the submit looks like it did nothing.
 */
export function alertMessageOf(error: ApiError | null): string {
  if (error === null) return "";
  if (error.formError) return error.formError;
  return Object.keys(error.fieldErrors).length > 0 ? "입력한 정보를 다시 확인해 주세요." : "";
}

/**
 * Drops the given fields' errors after the user edits one of them.
 *
 * More than one field is accepted because a rule can span two of them while its
 * message can only be filed under one — a mismatch reported on `password_confirm`
 * is equally the business of `password`, and editing either one settles it. The
 * caller decides which names travel together; this module has no opinion on the
 * form's shape.
 *
 * `formError` is deliberately left alone: it describes the submission as a
 * whole and is often the *only* thing on screen (a 409 duplicate email has no
 * field errors at all), so clearing it on an unrelated keystroke would leave a
 * failed form with no visible reason. It is reset at the next submit instead.
 *
 * Returns the same object when nothing changes, so React can skip the re-render.
 */
export function clearFieldErrors(
  error: ApiError | null,
  fields: readonly string[]
): ApiError | null {
  if (error === null) return null;

  const present = fields.filter((field) => field in error.fieldErrors);
  if (present.length === 0) return error;

  const fieldErrors = { ...error.fieldErrors };
  for (const field of present) delete fieldErrors[field];
  return { ...error, fieldErrors };
}

/** Single-field shorthand for {@link clearFieldErrors}. */
export function clearFieldError(error: ApiError | null, field: string): ApiError | null {
  return clearFieldErrors(error, [field]);
}

function labelOf(field: string): string {
  return FIELD_LABELS[field] ?? field;
}
