from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.routes.auth import router as auth_router
from app.routes.saved_score import router as saved_score_router
from app.routes.score import router as score_router

app = FastAPI(title="Hymn Backend")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    """Answers 422 without echoing the rejected value back to the caller.

    Pydantic puts the offending input in each item's `input` key. On /auth/signup
    that is the user's plaintext password, which would then reach browser
    devtools, HAR exports and anything that logs response bodies. `ctx` is kept:
    the client reads ctx.min_length/max_length to word its own messages.
    """
    detail = [{key: value for key, value in item.items() if key != "input"} for item in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(detail)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://staging.score-hymn.com",
        "https://staging.score-hymn.com",
        "https://www.score-hymn.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(score_router)
app.include_router(auth_router)
app.include_router(saved_score_router)

@app.get("/health")
def health():
    """Lightweight liveness probe."""
    return {"status": "ok"}


@app.get("/")
def root():
    return {"message": "Hello from Hymn backend"}
