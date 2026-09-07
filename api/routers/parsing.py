from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile

from api.dependencies import current_user, services
from parsing.extractors import MAX_RESUME_BYTES


router = APIRouter(prefix="/api/parsing", tags=["parsing"])


@router.get("/capabilities")
def capabilities(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return services(request).parsing.capabilities()


@router.post("/resume/extract")
async def extract_resume_file(
    request: Request,
    file: UploadFile = File(...),
    _: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    content = await file.read(MAX_RESUME_BYTES + 1)
    return {"extraction": services(request).parsing.extract_resume(file.filename or "", content), "persisted": False}


@router.post("/resume/preview")
async def resume_preview(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    payload = await request.json()
    return services(request).parsing.resume_preview(str(payload.get("text") or ""))


@router.post("/jd/preview")
async def jd_preview(request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    payload = await request.json()
    return services(request).parsing.jd_preview(str(payload.get("text") or ""))
