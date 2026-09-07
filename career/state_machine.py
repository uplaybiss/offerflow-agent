from __future__ import annotations

from career.models import APPLICATION_TRANSITIONS, ApplicationStatus
from core.errors import ConflictError, ValidationError


def validate_initial_application_status(status: str) -> str:
    normalized = str(status or ApplicationStatus.PLANNED.value).upper()
    allowed = {
        ApplicationStatus.PLANNED.value,
        ApplicationStatus.APPLIED.value,
    }
    if normalized not in allowed:
        raise ValidationError("普通创建投递只允许 PLANNED 或 APPLIED，其他状态必须通过迁移进入")
    return normalized


def validate_application_transition(current: str, target: str) -> None:
    target = str(target or "").upper()
    if target == current:
        raise ConflictError("目标状态与当前状态相同")
    if target not in APPLICATION_TRANSITIONS.get(current, set()):
        raise ConflictError(f"不允许从 {current} 迁移到 {target}")
