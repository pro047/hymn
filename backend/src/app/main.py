from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.score import router as score_router

app = FastAPI(title="Hymn Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(score_router)

@app.get("/health")
def health():
    """Lightweight liveness probe."""
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Hello from Hymn backend"}