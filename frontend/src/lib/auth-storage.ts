const ACCESS_TOKEN_KEY = "hymn_access_token";
const REFRESH_TOKEN_KEY = "hymn_refresh_token";

export type TokenPair = {
  accessToken: string;
  refreshToken: string;
};

export function getAccessToken(): string | null {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens({ accessToken, refreshToken }: TokenPair): void {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  // Legacy key written by older builds; nothing writes it anymore.
  localStorage.removeItem("hymn_church_code");
}

export function isAuthenticated(): boolean {
  return Boolean(getAccessToken());
}
