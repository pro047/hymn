import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "../lib/auth-storage";
import { API_PATHS } from "./paths";

type RefreshResult = "refreshed" | "rejected" | "transient";

// Callers only ever pass plain-object headers, which is what the spread in
// withAuthHeader() assumes. Headers/array forms would silently lose entries.
export type ApiFetchOptions = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
};

let refreshPromise: Promise<RefreshResult> | null = null;

// Bumped every time this tab tears its session down. A refresh started before
// the teardown carries the epoch it began under; if it changed by the time the
// response lands, the tokens it would write are for a session that no longer
// exists — writing them would silently revive a logged-out tab. Module-local,
// so it only guards this document; a logout in another tab is handled through
// storage instead (see the grace check below).
let sessionEpoch = 0;

// Exported so every teardown path — logout, a rejected refresh, a password
// change that revokes the caller's own tokens — goes through the one place that
// both clears storage and invalidates any in-flight refresh.
export function endSession(): void {
  sessionEpoch += 1;
  clearTokens();
}

function postRefreshToken(url: string, refreshToken: string, init: RequestInit = {}) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
    ...init,
  });
}

// Resolves to "refreshed" (retry with new tokens), "rejected" (session is
// gone, log out) or "transient" (server/network hiccup — keep tokens).
async function requestTokenRefresh(): Promise<RefreshResult> {
  const startedEpoch = sessionEpoch;
  const refreshToken = getRefreshToken();
  if (!refreshToken) return "rejected";

  let response: Response;
  try {
    response = await postRefreshToken(API_PATHS.authRefresh, refreshToken);
  } catch {
    return "transient";
  }

  // The session may have ended while this was in flight — an explicit logout,
  // or a redirect from another failed call. A success below would write fresh
  // tokens into storage we just cleared and revive the session; a 401 would
  // fall into the grace logic and read the now-empty storage as "another tab
  // refreshed for us". Both are wrong once we are logged out, so stop here.
  if (sessionEpoch !== startedEpoch) return "rejected";

  if (response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      access_token?: string;
      refresh_token?: string;
    } | null;
    if (!payload?.access_token || !payload?.refresh_token) return "transient";
    setTokens({ accessToken: payload.access_token, refreshToken: payload.refresh_token });
    return "refreshed";
  }

  if (response.status === 401) {
    // Refresh tokens are one-time: a 401 can mean another tab already spent
    // ours and rotated the pair. Only a *different, non-empty* token in storage
    // is evidence of that — an empty slot means the session is gone (a logout
    // in this or another tab), not that someone refreshed for us. Reading empty
    // as "refreshed" made apiFetch retry the original request with no auth
    // header at all, which for POST /auth/password meant re-sending the
    // plaintext body unauthenticated.
    const rotatedElsewhere = () => {
      const current = getRefreshToken();
      return Boolean(current) && current !== refreshToken;
    };
    if (rotatedElsewhere()) return "refreshed";
    await new Promise((resolve) => setTimeout(resolve, 750));
    return rotatedElsewhere() ? "refreshed" : "rejected";
  }

  return "transient";
}

function refreshTokens(): Promise<RefreshResult> {
  // Concurrent 401s in this tab must share a single in-flight refresh.
  if (!refreshPromise) {
    refreshPromise = requestTokenRefresh()
      .catch((): RefreshResult => "transient")
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

function redirectToLogin(): Promise<Response> {
  endSession();
  window.location.replace("/login");
  // The page is navigating away — never settle, so callers don't flash
  // error UI against a session that no longer exists.
  return new Promise<Response>(() => {});
}

export async function apiFetch(url: string, options: ApiFetchOptions = {}): Promise<Response> {
  const withAuthHeader = (): RequestInit => {
    const token = getAccessToken();
    return {
      ...options,
      headers: {
        ...(options.headers || {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    };
  };

  let response = await fetch(url, withAuthHeader());
  if (response.status !== 401) return response;

  const result = await refreshTokens();
  if (result === "transient") return response;
  if (result === "rejected") return redirectToLogin();

  response = await fetch(url, withAuthHeader());
  if (response.status === 401) return redirectToLogin();
  return response;
}

export function logout(): void {
  const refreshToken = getRefreshToken();
  // Bumps the epoch as well as clearing storage, so an in-flight refresh that
  // resolves after this returns cannot write its tokens back.
  endSession();
  if (refreshToken) {
    // Fire-and-forget revocation; keepalive lets it outlive the navigation.
    postRefreshToken(API_PATHS.authLogout, refreshToken, { keepalive: true }).catch(() => {});
  }
  window.location.replace("/login");
}
