from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from api.dependencies import admin_user, services


router = APIRouter(prefix="/api/agentops", tags=["agentops"])


class ConfigurationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=100)
    settings: dict[str, Any]


class ValidateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)


class PublishBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str
    channel: str
    canary_percent: float = 0
    expected_generation: int = Field(ge=0)
    command_id: str


class RollbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_version_id: str
    expected_generation: int = Field(ge=0)
    command_id: str
    reason: str = Field(default="", max_length=500)


class EvaluationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_name: str = "phase5-stable"
    update_baseline: bool = False


@router.get("/overview")
def overview(
    request: Request,
    window_minutes: int = Query(default=60, ge=1, le=1440),
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return services(request).agentops.overview(services(request).quality, window_minutes)


@router.get("/configurations")
def configurations(request: Request, _: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"items": services(request).agentops.store.list_configurations()}


@router.post("/configurations", status_code=201)
def create_configuration(
    body: ConfigurationBody,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {"configuration": services(request).agentops.create_configuration(body.model_dump(), user["username"])}


@router.post("/configurations/{version_id}/validate")
def validate_configuration(
    version_id: str,
    body: ValidateBody,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {
        "configuration": services(request).agentops.validate_configuration(
            version_id, body.expected_revision, user["username"]
        )
    }


@router.post("/releases")
def publish(
    body: PublishBody,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return services(request).agentops.publish(body.model_dump(), user["username"])


@router.post("/rollback")
def rollback(
    body: RollbackBody,
    request: Request,
    user: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return services(request).agentops.rollback(body.model_dump(), user["username"])


@router.get("/traces")
def traces(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    status: str = "",
    run_type: str = "",
    config_version_id: str = "",
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {
        "items": services(request).quality.list_runs(
            limit=limit,
            status=status,
            run_type=run_type,
            config_version_id=config_version_id,
        )
    }


@router.get("/traces/{trace_id}")
def trace_detail(
    trace_id: str,
    request: Request,
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {"trace": services(request).quality_management.trace(trace_id)}


@router.get("/evaluations")
def evaluations(request: Request, _: dict[str, Any] = Depends(admin_user)) -> dict[str, Any]:
    return {"items": services(request).quality.list_eval_runs()}


@router.post("/evaluations/run")
def run_evaluation(
    body: EvaluationBody,
    request: Request,
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {"evaluation": services(request).quality_management.run_fixed(body.model_dump())}


@router.post("/evaluations/replay")
def replay_evaluation(
    body: EvaluationBody,
    request: Request,
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {"evaluation": services(request).quality_management.run_fixed(body.model_dump(), replay=True)}


@router.get("/evaluations/{eval_run_id}")
def evaluation_detail(
    eval_run_id: str,
    request: Request,
    _: dict[str, Any] = Depends(admin_user),
) -> dict[str, Any]:
    return {"evaluation": services(request).quality_management.evaluation_run(eval_run_id)}
