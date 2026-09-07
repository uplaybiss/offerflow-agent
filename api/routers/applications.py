from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from api.dependencies import candidate_for, current_user, services


router = APIRouter(prefix="/api", tags=["applications"])


@router.get("/applications")
def list_applications(request: Request, status: str = "", user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"items": services(request).applications.list(candidate["candidate_id"], status)}


@router.post("/applications", status_code=201)
async def create_application(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).applications.create(candidate["candidate_id"], user["username"], await request.json())


@router.get("/applications/{application_id}")
def get_application(application_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"application": services(request).applications.get(candidate["candidate_id"], application_id)}


@router.post("/applications/{application_id}/transitions")
async def transition_application(application_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).applications.transition(
        candidate["candidate_id"], application_id, user["username"], await request.json()
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
async def create_interview(application_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"interview": services(request).interviews.create(candidate["candidate_id"], application_id, await request.json())}


@router.patch("/interviews/{round_id}")
async def update_interview(round_id: str, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"interview": services(request).interviews.update(candidate["candidate_id"], round_id, await request.json())}
