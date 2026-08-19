import { readApiError, toFormError, type ApiError } from "../lib/api-error";
import type { PasswordResetBody, PasswordResetRequestBody } from "../lib/validation/auth-schema";
import { endSession } from "./client";
import { API_PATHS } from "./paths";

export type PasswordResetOutcome = { ok: true } | { ok: false; error: ApiError };

const NETWORK_MESSAGE = "네트워크 연결을 확인한 뒤 다시 시도해 주세요.";

/**
 * Said whenever the link itself is the problem — absent, truncated, spent.
 *
 * The user cannot act on the distinction: there is no token input on the page,
 * so "16자 이상 입력해 주세요" would be an instruction they cannot follow. Every
 * one of these cases has the same remedy, which is what this sentence gives.
 * Exported so the page's own no-token branch says it too, rather than keeping a
 * second sentence that means the same thing.
 */
export const INVALID_LINK_MESSAGE =
  "재설정 링크가 올바르지 않습니다. 메일의 링크를 다시 열거나 재설정을 다시 요청해 주세요.";

/**
 * Said when the endpoint is not mounted at all.
 *
 * Both routes exist only while PASSWORD_RESET_ENABLED is set, and an unmounted
 * FastAPI route answers `{"detail": "Not Found"}` — a string, which
 * normalizeApiError passes straight through in place of any fallback. Left
 * alone, a Korean screen shows the user the English words "Not Found".
 */
const FEATURE_UNAVAILABLE_MESSAGE =
  "비밀번호 재설정을 지금은 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.";

// Field names each form renders inline. `token` is listed for the confirm call
// even though nothing renders it: that keeps a token rejection out of the alert
// as `token: …` — labelOf() falls back to the raw field name — and lets the
// caller below swap in a sentence the user can act on.
const REQUEST_RENDERED_FIELDS = ["email"] as const;
const CONFIRM_RENDERED_FIELDS = ["new_password", "token"] as const;

/**
 * Both calls go through plain `fetch`, never `apiFetch`, and that is load-bearing
 * rather than incidental.
 *
 * Neither endpoint is authenticated, so the Authorization header apiFetch adds
 * would be meaningless. The reason it would be actively wrong is the confirm
 * call: the server answers a spent or expired link with 401, and apiFetch reads
 * every 401 as an expired access token. It would refresh, find no refresh token,
 * classify the session as gone and call redirectToLogin() — which returns a
 * promise that never settles, by design, so the page would hang on "처리 중"
 * and then be replaced by /login. The user would never see the sentence
 * explaining that their link expired.
 *
 * The change form (api/password.ts) can use apiFetch precisely because the
 * server chose 403 there instead. This is the same trade seen from the other
 * side, not an inconsistency.
 */
async function postJson(url: string, body: unknown): Promise<Response | null> {
  try {
    return await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // fetch() rejects only on transport failure, so this is the one place where
    // blaming the connection is actually true.
    return null;
  }
}

/**
 * Asks for a reset link.
 *
 * The server answers 202 with an empty body for every address, registered or
 * not, so `ok: true` says the request was accepted and nothing at all about
 * whether an account exists. The caller must word its confirmation the same way
 * — a screen that says "메일을 보냈습니다" would rebuild, in copy, the
 * enumeration oracle the 202 exists to close.
 */
export async function requestPasswordReset(
  body: PasswordResetRequestBody
): Promise<PasswordResetOutcome> {
  const response = await postJson(API_PATHS.authPasswordResetRequest, body);
  if (response === null) return { ok: false, error: toFormError(NETWORK_MESSAGE) };
  if (response.status === 404)
    return { ok: false, error: toFormError(FEATURE_UNAVAILABLE_MESSAGE) };

  if (!response.ok) {
    return {
      ok: false,
      // 429 arrives in the same {detail: "…"} shape every other error uses, so
      // the rate limiter's own sentence flows through without special casing.
      error: await readApiError(
        response,
        "요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        REQUEST_RENDERED_FIELDS
      ),
    };
  }

  return { ok: true };
}

/**
 * Sets the new password from a mailed link and drops any session in this browser.
 *
 * The server answers 204 and hands back no token pair on purpose: a reset is the
 * recovery path for an account that may be in someone else's hands, so the user
 * re-authenticates rather than being given a live session by an unauthenticated
 * request.
 *
 * endSession() runs because the link may well be opened in a browser that is
 * still signed in — the mail arrives wherever the user reads mail. The confirm
 * revokes every session server-side, so tokens left in storage are already dead;
 * clearing them here means the next request does not have to discover that. It
 * is endSession rather than clearTokens for the reason api/password.ts gives: an
 * unrelated in-flight refresh must not resolve afterwards and write a fresh pair
 * back over the teardown.
 */
export async function confirmPasswordReset(body: PasswordResetBody): Promise<PasswordResetOutcome> {
  const response = await postJson(API_PATHS.authPasswordResetConfirm, body);
  if (response === null) return { ok: false, error: toFormError(NETWORK_MESSAGE) };
  if (response.status === 404)
    return { ok: false, error: toFormError(FEATURE_UNAVAILABLE_MESSAGE) };

  if (!response.ok) {
    const error = await readApiError(
      response,
      "비밀번호를 재설정하지 못했습니다.",
      CONFIRM_RENDERED_FIELDS
    );
    // A 401 (spent or expired link) already arrives as a sentence in `detail`
    // and is left alone. This is the 422 case — a truncated link — where the
    // server describes a length the user has no field to correct.
    if ("token" in error.fieldErrors) {
      return { ok: false, error: toFormError(INVALID_LINK_MESSAGE) };
    }
    return { ok: false, error };
  }

  endSession();
  return { ok: true };
}
