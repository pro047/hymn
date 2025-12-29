from fastapi import FastAPI

app = FastAPI(title="Hymn Backend")


@app.get("/health")
def health():
    """Lightweight liveness probe."""
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Hello from Hymn backend"}
