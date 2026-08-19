const API_BASE = import.meta.env.VITE_API_BASE_URL;

export const API_PATHS = {
  scores: `${API_BASE}/scores`,
  score: (scoreId: string) => `${API_BASE}/scores/${scoreId}`,
  savedScores: `${API_BASE}/me/saved-scores`,
  savedScoreUpload: `${API_BASE}/me/saved-scores/upload`,
  savedScore: (scoreId: string) => `${API_BASE}/me/saved-scores/${scoreId}`,
  applySavedScore: (scoreId: string) => `${API_BASE}/me/saved-scores/${scoreId}/apply`,
  // The address goes in the query string, so it must be escaped: `+` and `&` are
  // legal in a local part and would otherwise be read as syntax.
  authCheckEmail: (email: string) =>
    `${API_BASE}/auth/check-email?email=${encodeURIComponent(email)}`,
  // Church names are Korean and contain spaces, so escaping is not optional
  // here either — an unescaped one would be a malformed URL, not just an odd
  // query string.
  authCheckChurch: (name: string) =>
    `${API_BASE}/auth/check-church?name=${encodeURIComponent(name)}`,
  authChurchJoinCode: `${API_BASE}/auth/church/join-code`,
  authLogin: `${API_BASE}/auth/login`,
  authSignup: `${API_BASE}/auth/signup`,
  authMe: `${API_BASE}/auth/me`,
  authPassword: `${API_BASE}/auth/password`,
  // Both live behind PASSWORD_RESET_ENABLED on the server, so a deployment
  // without that flag answers 404 here rather than 202/204.
  authPasswordResetRequest: `${API_BASE}/auth/password-reset/request`,
  authPasswordResetConfirm: `${API_BASE}/auth/password-reset/confirm`,
  authRefresh: `${API_BASE}/auth/refresh`,
  authLogout: `${API_BASE}/auth/logout`,
};
