const API_BASE = import.meta.env.VITE_API_BASE_URL;

export const API_PATHS = {
  scores: `${API_BASE}/scores`,
  score: (scoreId) => `${API_BASE}/scores/${scoreId}`,
  savedScores: `${API_BASE}/me/saved-scores`,
  savedScoreUpload: `${API_BASE}/me/saved-scores/upload`,
  savedScore: (scoreId) => `${API_BASE}/me/saved-scores/${scoreId}`,
  applySavedScore: (scoreId) => `${API_BASE}/me/saved-scores/${scoreId}/apply`,
  authLogin: `${API_BASE}/auth/login`,
  authSignup: `${API_BASE}/auth/signup`,
  authMe: `${API_BASE}/auth/me`,
};
