import { clearTokens, getAccessToken, getRefreshToken, setTokens } from "../lib/auth-storage";
import { API_PATHS } from "./paths";

type RefreshResult = "refreshed" | "rejected" | "transient";

// Callers only ever pass plain-object headers, which is what the spread in
// withAuthHeader() assumes. Headers/array forms would silently lose entries.
export type ApiFetchOptions = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
};

let refreshPromise: Promise<RefreshResult> | null = null;

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
  const refreshToken = getRefreshToken();
  if (!refreshToken) return "rejected";

  let response: Response;
  try {
    response = await postRefreshToken(API_PATHS.authRefresh, refreshToken);
  } catch {
    return "transient";
  }

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
    // ours and rotated the pair. If storage holds a different token (now or
    // after a short grace period for the other tab's response to land),
    // that tab refreshed for us — don't wipe its valid tokens.
    if (getRefreshToken() !== refreshToken) return "refreshed";
    await new Promise((resolve) => setTimeout(resolve, 750));
    return getRefreshToken() !== refreshToken ? "refreshed" : "rejected";
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
  clearTokens();
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
  clearTokens();
  if (refreshToken) {
    // Fire-and-forget revocation; keepalive lets it outlive the navigation.
    postRefreshToken(API_PATHS.authLogout, refreshToken, { keepalive: true }).catch(() => {});
  }
  window.location.replace("/login");
}
