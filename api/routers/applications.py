from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from api.dependencies import candidate_for, current_user, services
from api.schemas import (
    ApplicationCreateBody,
    ApplicationTransitionBody,
    InterviewCreateBody,
    InterviewUpdateBody,
    body_dict,
)
from career.models import APPLICATION_TRANSITIONS


router = APIRouter(prefix="/api", tags=["applications"])


@router.get("/applications/transitions/config")
def transition_config(_: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"transitions": {status: sorted(targets) for status, targets in APPLICATION_TRANSITIONS.items()}}


@router.get("/applications")
def list_applications(request: Request, status: str = "", user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"items": services(request).applications.list(candidate["candidate_id"], status)}


@router.post("/applications", status_code=201)
def create_application(body: ApplicationCreateBody, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).applications.create(candidate["candidate_id"], user["username"], body_dict(body))


@router.get("/applications/{application_id}")
def get_application(application_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"application": services(request).applications.get(candidate["candidate_id"], application_id)}


@router.post("/applications/{application_id}/transitions")
def transition_application(application_id: str, body: ApplicationTransitionBody, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).applications.transition(
        candidate["candidate_id"], application_id, user["username"], body_dict(body)
    )


@router.get("/interviews")
def list_interviews(
    request: Request,
    application_id: str = "",
    upcoming_only: bool = Query(False),
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"items": services(request).interviews.list(candidate["candidate_id"], application_id, upcoming_only)}


@router.post("/applications/{application_id}/interviews", status_code=201)
def create_interview(application_id: str, body: InterviewCreateBody, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"interview": services(request).interviews.create(candidate["candidate_id"], application_id, body_dict(body))}


@router.patch("/interviews/{round_id}")
def update_interview(round_id: str, body: InterviewUpdateBody, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"interview": services(request).interviews.update(candidate["candidate_id"], round_id, body_dict(body))}
