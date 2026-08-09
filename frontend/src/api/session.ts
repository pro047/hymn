import { readApiError, toFormError, type ApiError } from "../lib/api-error";
import { apiFetch } from "./client";
import { API_PATHS } from "./paths";

export type Session = {
  role: string;
  churchName: string;
  /** Null for a member: the server only shows the invite code to its leader. */
  churchCode: string | null;
};

/**
 * Reads the signed-in session from GET /auth/me.
 *
 * Through apiFetch, so an expired access token is refreshed and retried rather
 * than being reported as "not a leader". Returns null for anything that is not
 * a readable session — the callers use this to decide whether to offer the
 * church management screen, and hiding it is the safe answer to a bad reply.
 */
export async function fetchSession(): Promise<Session | null> {
  try {
    const response = await apiFetch(API_PATHS.authMe);
    if (!response.ok) return null;

    const payload = (await response.json()) as {
      user?: { role?: unknown };
      church?: { name?: unknown; code?: unknown };
    };
    if (typeof payload.user?.role !== "string") return null;

    return {
      role: payload.user.role,
      churchName: typeof payload.church?.name === "string" ? payload.church.name : "",
      churchCode: typeof payload.church?.code === "string" ? payload.church.code : null,
    };
  } catch {
    return null;
  }
}

export type RotateOutcome = { ok: true; code: string } | { ok: false; error: ApiError };

/**
 * Issues a new invite code, retiring the current one. Leader only — the server
 * answers 403 to anyone else, and its wording is what gets shown.
 */
export async function rotateJoinCode(): Promise<RotateOutcome> {
  let response: Response;
  try {
    response = await apiFetch(API_PATHS.authChurchJoinCode, { method: "POST" });
  } catch {
    return { ok: false, error: toFormError("네트워크 연결을 확인한 뒤 다시 시도해 주세요.") };
  }

  if (!response.ok) {
    return {
      ok: false,
      error: await readApiError(response, "초대 코드를 재발급하지 못했습니다.", []),
    };
  }

  const payload = (await response.json().catch(() => null)) as { code?: unknown } | null;
  if (typeof payload?.code !== "string") {
    // The old code has already stopped working at this point, so this must not
    // read as "nothing happened" — reloading is how the caller recovers.
    return {
      ok: false,
      error: toFormError("코드는 재발급됐지만 화면에 표시하지 못했습니다. 새로고침해 주세요."),
    };
  }
  return { ok: true, code: payload.code };
}
