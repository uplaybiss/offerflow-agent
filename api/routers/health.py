from __future__ import annotations

from fastapi import APIRouter

from core.time import timezone_name, utc_now


router = APIRouter(tags=["health"])


@router.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "offerflow-api", "utc_time": utc_now(), "timezone": timezone_name()}
