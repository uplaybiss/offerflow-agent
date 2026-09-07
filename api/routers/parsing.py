from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Request, UploadFile

from api.dependencies import current_user, services
from api.schemas import TextPreviewBody
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
def resume_preview(body: TextPreviewBody, request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return services(request).parsing.resume_preview(body.text)


@router.post("/jd/preview")
def jd_preview(body: TextPreviewBody, request: Request, _: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return services(request).parsing.jd_preview(body.text)
