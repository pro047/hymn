import logging

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.rate_limit import HEALTH_READY_LIMIT, limiter, rate_limit_handler
from app.routes.auth import PASSWORD_RESET_ENABLED, password_reset_router
from app.routes.auth import router as auth_router
from app.routes.conti import router as conti_router
from app.routes.score import router as score_router
from app.routes.song import router as song_router
from app.utils.email import require_deliverable_transport

logger = logging.getLogger(__name__)

app = FastAPI(title="Hymn Backend")

# slowapi's decorator reads the limiter off the app it is serving, so this
# assignment is what makes @limiter.limit(...) in the routers do anything.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_handler)


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
    allow_headers=["*"],
    # allow_headers is about the *request*; a cross-origin reader sees only
    # the CORS-safelisted response headers unless they are named here. The
    # conti PDF route sends the week's normalized name in Content-Disposition
    # (routes/conti.py) and the browser silently drops it without this, so the
    # download quietly fell back to the client's own guess at the filename.
    expose_headers=["Content-Disposition"],
)

app.include_router(score_router)
app.include_router(auth_router)
app.include_router(song_router)
app.include_router(conti_router)
if PASSWORD_RESET_ENABLED:
    # Before the mount, not after: if the transport cannot deliver in this
    # environment the route must not come into existence at all.
    require_deliverable_transport()
    app.include_router(password_reset_router)

@app.get("/health")
def health():
    """Lightweight liveness probe."""
    return {"status": "ok"}


@app.get("/health/ready")
@limiter.limit(HEALTH_READY_LIMIT)
def health_ready(request: Request, session: Session = Depends(get_session)) -> JSONResponse:
    """Whether a request that needs the database would succeed right now.

    Separate from /health on purpose. The deploy script polls /health to decide
    whether the new container came up (deploy.yml), and that question must not
    start depending on the database; this one is for the uptime monitor, where
    "the process is alive but nothing works" has to count as down.

    The driver's message names the host and the user, so it goes to the log and
    the caller gets only the status.
    """
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        logger.exception("readiness probe could not reach the database")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(content={"status": "ok"})


@app.get("/")
def root():
    return {"message": "Hello from Hymn backend"}
