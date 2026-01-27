const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export const API_PATHS = {
  scores: `${API_BASE}/scores`,
  score: (scoreId) => `${API_BASE}/scores/${scoreId}`,
}
