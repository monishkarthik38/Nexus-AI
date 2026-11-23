import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database.session import AsyncSessionLocal, engine, init_db
from app.ingestion.worker import IngestionWorker
from app.api.health import router as health_router
from app.api.documents import router as documents_router
from app.api.chat import router as chat_router
from app.api.evaluation import router as evaluation_router
from app.api.annotations import router as annotations_router
from app.api.reports import router as reports_router

logger = logging.getLogger(__name__)


def _log_worker_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "Development ingestion worker stopped unexpectedly (%s)",
            type(error).__name__,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate settings, apply development schema setup, or verify production RLS.
    await init_db()
    worker_task = None
    if (
        settings.ENVIRONMENT.strip().lower() == "development"
        and not settings.INGESTION_INLINE_DEVELOPMENT
        and engine.dialect.name == "sqlite"
    ):
        worker_task = asyncio.create_task(
            IngestionWorker(AsyncSessionLocal).run_forever(),
            name="sqlite-ingestion-worker",
        )
        worker_task.add_done_callback(_log_worker_exit)
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass

app = FastAPI(
    title="Nexus AI - Agentic Knowledge & Research API",
    description="Backend API for Nexus AI: Source-grounded RAG & Agentic Document Research",
    version="0.1.0",
    lifespan=lifespan
)

# CORS setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"] + (["X-Dev-User"] if settings.AUTH_MODE == "development" else []),
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if "server" in response.headers:
        del response.headers["server"]
    return response

# Register routes
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(evaluation_router)
app.include_router(annotations_router)
app.include_router(reports_router)

@app.get("/")
async def root():
    return {
        "message": "Welcome to Nexus AI API. Explore /docs for interactive API documentation.",
        "health": "/health",
        "documents": "/api/documents",
        "chat": "/api/chat",
        "reports": "/api/reports",
        "evaluation": "/api/evaluation/run"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
