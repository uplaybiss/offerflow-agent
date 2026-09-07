from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from api.dependencies import candidate_for, current_user, services


router = APIRouter(prefix="/api/task-suggestions", tags=["task-suggestions"])


@router.get("")
def list_suggestions(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).suggestions.list(candidate["candidate_id"])


@router.post("/{suggestion_key}/accept", status_code=201)
def accept_suggestion(
    suggestion_key: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    candidate = candidate_for(request, user)
    return services(request).suggestions.accept(candidate["candidate_id"], suggestion_key)
