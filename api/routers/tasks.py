from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from api.dependencies import candidate_for, current_user, services
from api.schemas import TaskCreateBody, TaskUpdateBody, body_dict


router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks")
def list_tasks(request: Request, status: str = "", user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"items": services(request).tasks.list(candidate["candidate_id"], status)}


@router.post("/tasks", status_code=201)
def create_task(body: TaskCreateBody, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"task": services(request).tasks.create(candidate["candidate_id"], body_dict(body))}


@router.patch("/tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdateBody, request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return {"task": services(request).tasks.update(candidate["candidate_id"], task_id, body_dict(body))}


@router.get("/workbench")
def workbench(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).workbench.overview(candidate["candidate_id"])
