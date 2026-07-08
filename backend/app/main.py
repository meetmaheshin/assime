"""FastAPI app factory for AARTH (Artificial Assistant & Reconciliation To Human)."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    auth, chat, connections, delegation, notifications, planning, projects,
    push, tasks, voice,
)
from app.core.config import settings
from app.services.scheduler import start_scheduler, stop_scheduler

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()  # background nudge generation + web push
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    app = FastAPI(
        title="AARTH API",
        version="0.1.0",
        description="AI Personal Assistant backend — tasks, projects, memory, chat.",
        lifespan=lifespan,
    )

    # API auth is via bearer tokens (not cookies), so a wildcard origin is safe
    # and lets any client — the web PWA or a native mobile app — connect.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["meta"])
    async def health() -> dict:
        # Bump `version` on meaningful changes so we can confirm what's deployed.
        return {
            "status": "ok", "env": settings.env, "version": "build-48",
            "llm_provider": settings.resolved_provider,
            "reasoning_model": settings.azure_deployment_reasoning,
            "api_mode": "v1" if settings.azure_v1_base else "classic",
        }

    @app.get("/health/llm", tags=["meta"], include_in_schema=False)
    async def health_llm() -> dict:
        from app.services.agent import TOOLS
        from app.services.llm import build_chat_client, chat_create
        info = {"model": settings.azure_deployment_reasoning}
        try:
            client, model = build_chat_client()
            resp = await chat_create(
                client, model,
                messages=[{"role": "user", "content": "remind me to call bank at 4pm"}],
                tools=TOOLS, tool_choice="auto")
            info["ok"] = True
            info["used_model"] = resp.model
            m = resp.choices[0].message
            info["reply"] = (m.content or "")[:60]
            info["tool_calls"] = [t.function.name for t in (m.tool_calls or [])]
        except Exception as e:  # noqa: BLE001
            info["ok"] = False
            info["error"] = f"{type(e).__name__}: {str(e)[:400]}"
        return info

    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(tasks.router)
    app.include_router(chat.router)
    app.include_router(planning.router)
    app.include_router(voice.router)
    app.include_router(notifications.router)
    app.include_router(push.router)
    app.include_router(connections.router)
    app.include_router(delegation.router)

    # Serve the web demo client from the same origin (no CORS needed).
    if WEB_DIR.is_dir():
        @app.get("/", include_in_schema=False)
        async def root() -> RedirectResponse:
            return RedirectResponse(url="/ui/")

        app.mount("/ui", StaticFiles(directory=str(WEB_DIR), html=True), name="ui")

    return app


app = create_app()
