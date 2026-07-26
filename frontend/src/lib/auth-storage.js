const ACCESS_TOKEN_KEY = "hymn_access_token";
const REFRESH_TOKEN_KEY = "hymn_refresh_token";

export function getAccessToken() {
  return localStorage.getItem(ACCESS_TOKEN_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setTokens({ accessToken, refreshToken }) {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
}

export function clearTokens() {
  localStorage.removeItem(ACCESS_TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  // Legacy key written by older builds; nothing writes it anymore.
  localStorage.removeItem("hymn_church_code");
}

export function isAuthenticated() {
  return Boolean(getAccessToken());
}
