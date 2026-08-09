import { readApiError, toFormError, type ApiError } from "../lib/api-error";
import { clearTokens } from "../lib/auth-storage";
import type { PasswordChangeBody } from "../lib/validation/auth-schema";
import { apiFetch } from "./client";
import { API_PATHS } from "./paths";

export type PasswordChangeOutcome = { ok: true } | { ok: false; error: ApiError };

// Field names the account form renders inline. Anything else — a rule on a
// field this form does not show — is promoted to the alert rather than dropped.
const RENDERED_FIELDS = ["current_password", "new_password"] as const;

/**
 * Changes the signed-in user's password and drops the now-dead session.
 *
 * The server answers 204 and revokes every refresh token the account had, this
 * tab's included, so the tokens in storage are worthless the moment this
 * returns. Clearing them here rather than in the page keeps "the session is
 * gone" attached to the request that ended it — a caller that forgets would
 * keep a dead pair around until its next 401.
 *
 * A wrong current password comes back as 403, not 401, and that is what makes
 * this callable through apiFetch at all: apiFetch reads a 401 as an expired
 * access token, refreshes, retries and signs the user out when the retry fails
 * the same way — so a typo in one field would end the session. With 403 the
 * server's own wording flows straight through, and a genuinely expired token
 * still gets refreshed and retried the way every other call does.
 */
export async function changePassword(body: PasswordChangeBody): Promise<PasswordChangeOutcome> {
  let response: Response;
  try {
    response = await apiFetch(API_PATHS.authPassword, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    return { ok: false, error: toFormError("네트워크 연결을 확인한 뒤 다시 시도해 주세요.") };
  }

  if (!response.ok) {
    return {
      ok: false,
      error: await readApiError(response, "비밀번호를 변경하지 못했습니다.", RENDERED_FIELDS),
    };
  }

  // No body to read: 204. The tokens are already revoked server-side, so
  // leaving them in storage would only mean the next request discovers that.
  clearTokens();
  return { ok: true };
}
