import { readApiError, toFormError, type ApiError } from "../lib/api-error";
import type { TokenPair } from "../lib/auth-storage";

export type AuthOutcome = { ok: true; tokens: TokenPair } | { ok: false; error: ApiError };

type AuthResponseBody = {
  tokens?: { access_token?: string; refresh_token?: string };
};

export type AuthRequest = {
  url: string;
  body: Record<string, unknown>;
  /** Alert copy when the server rejects the request without saying why. */
  failureMessage: string;
  /**
   * Alert copy when the server accepted the request but the token pair could
   * not be read back. The account/session already exists at that point, so the
   * message must not tell the user to simply retry.
   */
  unreadableMessage: string;
  /** Field names the calling form renders inline; see normalizeApiError. */
  renderedFields: readonly string[];
};

/**
 * Runs one login/signup POST and reduces every outcome to either a token pair
 * or a renderable ApiError. Both auth pages share this so their error copy and
 * response handling cannot drift apart.
 */
export async function requestAuth({
  url,
  body,
  failureMessage,
  unreadableMessage,
  renderedFields,
}: AuthRequest): Promise<AuthOutcome> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    // fetch() rejects only on transport failure, so this is the one place where
    // blaming the connection is actually true.
    return { ok: false, error: toFormError("네트워크 연결을 확인한 뒤 다시 시도해 주세요.") };
  }

  if (!response.ok) {
    return { ok: false, error: await readApiError(response, failureMessage, renderedFields) };
  }

  // A mangled body on a 2xx must not be reported as a failed request: the
  // server already committed the signup.
  const payload = (await response.json().catch(() => null)) as AuthResponseBody | null;
  const accessToken = payload?.tokens?.access_token;
  const refreshToken = payload?.tokens?.refresh_token;
  if (!accessToken || !refreshToken) {
    return { ok: false, error: toFormError(unreadableMessage) };
  }

  return { ok: true, tokens: { accessToken, refreshToken } };
}
