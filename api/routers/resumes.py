from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from api.dependencies import candidate_for, current_user, services
from api.schemas import (
    ResumeTailoringBody,
    ResumeVersionCopyBody,
    ResumeVersionCreateBody,
    ResumeVersionUpdateBody,
    body_dict,
)


router = APIRouter(prefix="/api", tags=["resume-workspace"])


@router.get("/resume-versions")
def list_versions(
    request: Request,
    include_archived: bool = Query(False),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"items": services(request).resumes.list(candidate["candidate_id"], include_archived)}


@router.post("/resume-versions", status_code=201)
def create_version(
    body: ResumeVersionCreateBody,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"resume_version": services(request).resumes.create(candidate, body_dict(body))}


@router.get("/resume-versions/{resume_version_id}")
def get_version(
    resume_version_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"resume_version": services(request).resumes.get(candidate["candidate_id"], resume_version_id)}


@router.patch("/resume-versions/{resume_version_id}")
def update_version(
    resume_version_id: str,
    body: ResumeVersionUpdateBody,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {
        "resume_version": services(request).resumes.update(
            candidate["candidate_id"], resume_version_id, body_dict(body)
        )
    }


@router.post("/resume-versions/{resume_version_id}/copy", status_code=201)
def copy_version(
    resume_version_id: str,
    body: ResumeVersionCopyBody,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {
        "resume_version": services(request).resumes.copy(
            candidate, resume_version_id, body.title
        )
    }


@router.post("/resume-tailoring/analyze")
def analyze_resume(
    body: ResumeTailoringBody,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {
        "analysis": services(request).resumes.analyze(
            candidate, body.job_id, resume_version_id=body.resume_version_id
        )
    }

