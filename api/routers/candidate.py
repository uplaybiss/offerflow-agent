from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from api.dependencies import current_user, services


router = APIRouter(prefix="/api/candidate", tags=["candidate"])


@router.get("")
def get_candidate(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return {"candidate": services(request).candidate.get(user["username"])}


@router.put("")
async def update_candidate(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    payload = await request.json()
    return {"candidate": services(request).candidate.update(user["username"], payload)}
