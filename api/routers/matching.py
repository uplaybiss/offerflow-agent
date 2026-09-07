from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from api.dependencies import candidate_for, current_user, services
from api.schemas import CompareJobsBody


router = APIRouter(prefix="/api", tags=["matching"])


@router.get("/matching/config")
def matching_config(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return services(request).matching.config()


@router.get("/jobs/{job_id}/match")
def match_job(job_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"match": services(request).matching.match_job(candidate, job_id)}


@router.post("/jobs/compare")
def compare_jobs(body: CompareJobsBody, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"comparison": services(request).matching.compare(candidate, body.job_ids)}


@router.post("/jobs/{job_id}/match/explanation")
def explain_match(job_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    result = services(request).matching.match_job(candidate, job_id)
    return {"match": result, **services(request).matching.explain(result)}
