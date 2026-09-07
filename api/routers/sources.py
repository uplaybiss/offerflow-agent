from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from api.dependencies import candidate_for, current_user, services


router = APIRouter(prefix="/api", tags=["sources"])


@router.get("/sources/capabilities")
def source_capabilities(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return services(request).sources.capabilities()


@router.post("/jobs/{job_id}/source-refresh")
def source_refresh_preview(
    job_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).sources.preview(candidate["candidate_id"], job_id)
