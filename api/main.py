from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from agent.runner import AgentRunner
from api.routers import agent, agentops, applications, auth, candidate, health, jobs, matching, parsing, sources, suggestions, tasks
from core.container import build_services
from core.database import Database, database_path
from core.errors import OfferFlowError
from parsing.llm import LlmClient
from sources.adapters import SourceAdapterRegistry


load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def create_app(
    *,
    db_path: str | None = None,
    session_secret: str | None = None,
    bootstrap_users: bool = True,
    llm_client: LlmClient | None = None,
    source_registry: SourceAdapterRegistry | None = None,
    quality_path: str | None = None,
    agentops_path: str | None = None,
    agent_runner: AgentRunner | None = None,
) -> FastAPI:
    resolved_db_path = db_path or database_path()
    database = Database(resolved_db_path)
    database.initialize()
    resolved_quality_path = quality_path
    if resolved_quality_path is None and db_path is not None:
        resolved_quality_path = str(Path(resolved_db_path).with_suffix(".quality.db"))
    resolved_agentops_path = agentops_path
    if resolved_agentops_path is None and db_path is not None:
        resolved_agentops_path = str(Path(resolved_db_path).with_suffix(".agentops.db"))
    service_container = build_services(
        database,
        llm_client=llm_client,
        source_registry=source_registry,
        quality_path=resolved_quality_path,
        agentops_path=resolved_agentops_path,
        agent_runner=agent_runner,
    )
    if bootstrap_users:
        service_container.auth.bootstrap_local_users()

    app = FastAPI(title="OfferFlow API", version="5.1.0-rc1")
    app.state.services = service_container
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret or os.getenv("SESSION_SECRET", "offerflow-local-change-me"),
        same_site="lax",
        https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        max_age=60 * 60 * 12,
    )
    origins = [item.strip() for item in os.getenv("FRONTEND_ORIGIN", "http://localhost:5173").split(",") if item.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(OfferFlowError)
    async def offerflow_error(_: Request, exc: OfferFlowError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": {"code": exc.code, "message": str(exc)}})

    @app.exception_handler(ValueError)
    async def value_error(_: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": {"code": "validation_error", "message": str(exc)}})

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(candidate.router)
    app.include_router(jobs.router)
    app.include_router(applications.router)
    app.include_router(tasks.router)
    app.include_router(parsing.router)
    app.include_router(matching.router)
    app.include_router(suggestions.router)
    app.include_router(sources.router)
    app.include_router(agent.router)
    app.include_router(agentops.router)

    frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    assets = frontend_dist / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> Any:
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        index = frontend_dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(status_code=404, content={"detail": "Frontend has not been built"})

    return app


app = create_app()
