"""FastAPI application factory for JARVIS."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, chat, projects, tasks
from app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup/shutdown hooks go here (e.g. Redis pool). Kept minimal for MVP.
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="JARVIS API",
        version="0.1.0",
        description="AI Personal Assistant backend — tasks, projects, memory, chat.",
        lifespan=lifespan,
    )

    # Dev CORS is open; tighten to the app's origins before production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.is_dev else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        return {"status": "ok", "env": settings.env}

    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(chat.router)
    return app


app = create_app()
