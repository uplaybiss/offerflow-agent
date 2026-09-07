from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from api.dependencies import candidate_for, current_user, services


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    request: Request,
    search: str = "",
    status: str = "",
    favorite_only: bool = Query(False),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    items = services(request).jobs.list(
        candidate["candidate_id"], search=search, status=status, favorite_only=favorite_only
    )
    return {"items": items}


@router.post("", status_code=201)
async def create_job(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"job": services(request).jobs.create(candidate["candidate_id"], await request.json())}


@router.get("/{job_id}")
def get_job(job_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"job": services(request).jobs.get(candidate["candidate_id"], job_id)}


@router.patch("/{job_id}")
async def update_job(job_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"job": services(request).jobs.update(candidate["candidate_id"], job_id, await request.json())}
