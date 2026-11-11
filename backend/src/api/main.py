import logging
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from src.api.routes import router
from src.config import settings
from src.service.logging import configure_logging, log_event, reset_trace_id, set_trace_id

FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend" / "dist"

configure_logging(level=settings.log_level, fmt=settings.log_format)
logger = logging.getLogger(__name__)

_TRACE_HEADER = "X-Trace-Id"
_TRACE_SANITIZER = re.compile(r"[^A-Za-z0-9_-]")


@asynccontextmanager
async def lifespan(_: FastAPI):
    log_event(logger, "app.startup", **settings.describe())
    yield
    log_event(logger, "app.shutdown")


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[_TRACE_HEADER],
)


@app.middleware("http")
async def trace_id_middleware(request: Request, call_next):
    """Bind one trace id to every request and echo it back in the response."""
    incoming = _TRACE_SANITIZER.sub("", request.headers.get("x-request-id", ""))[:64]
    trace_id = incoming or uuid4().hex[:16]
    token = set_trace_id(trace_id)
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        log_event(
            logger,
            "http.request.failed",
            level=logging.ERROR,
            exc_info=True,
            method=request.method,
            path=request.url.path,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        reset_trace_id(token)
        raise

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    response.headers[_TRACE_HEADER] = trace_id
    log_event(
        logger,
        "http.request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
    )
    reset_trace_id(token)
    return response


app.include_router(router, prefix="/api")


def _mount_frontend() -> None:
    """Serve the built SPA from the API container when it exists.

    Local development keeps using the Vite dev server; a deployment can ship a
    single container with no CORS surface at all.
    """
    if not (FRONTEND_DIST / "index.html").is_file():
        return

    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa_fallback(path: str) -> FileResponse:
        candidate = (FRONTEND_DIST / path).resolve()
        if candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        if "." in Path(path).name:
            # A missing asset must 404, not silently return index.html.
            raise HTTPException(status_code=404, detail="Not found")
        return FileResponse(FRONTEND_DIST / "index.html")


_mount_frontend()
