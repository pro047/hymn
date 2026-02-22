const API_BASE = import.meta.env.VITE_API_BASE_URL;

export const API_PATHS = {
  scores: `${API_BASE}/scores`,
  score: (scoreId) => `${API_BASE}/scores/${scoreId}`,
  authLogin: `${API_BASE}/auth/login`,
  authMe: `${API_BASE}/auth/me`,
};
