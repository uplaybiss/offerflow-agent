from __future__ import annotations

import hashlib
from typing import Any

from career.repositories.candidate import CandidateRepository
from core.errors import ValidationError
from core.time import utc_now


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} 必须是数组")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


class CandidateService:
    def __init__(self, repository: CandidateRepository) -> None:
        self.repository = repository

    def get(self, username: str) -> dict[str, Any]:
        return self.repository.get_or_create(username)

    def update(self, username: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get(username)
        try:
            expected_version = int(payload.get("version"))
        except (TypeError, ValueError):
            raise ValidationError("version 必须是整数") from None
        resume_text = str(payload.get("current_resume_text", current["current_resume_text"]) or "")
        if len(resume_text) > 500_000:
            raise ValidationError("当前简历文本过长")
        parsed = payload.get("current_resume_parsed", current["current_resume_parsed"])
        preferences = payload.get("preferences", current["preferences"])
        if not isinstance(parsed, dict) or not isinstance(preferences, dict):
            raise ValidationError("简历解析结构和偏好必须是 JSON 对象")
        values = {
            "full_name": str(payload.get("full_name", current["full_name"]) or "").strip()[:100],
            "email": str(payload.get("email", current["email"]) or "").strip()[:200],
            "phone": str(payload.get("phone", current["phone"]) or "").strip()[:50],
            "graduation_year": str(payload.get("graduation_year", current["graduation_year"]) or "").strip()[:20],
            "degree": str(payload.get("degree", current["degree"]) or "").strip()[:100],
            "target_roles": _string_list(payload.get("target_roles", current["target_roles"]), "target_roles"),
            "preferred_cities": _string_list(payload.get("preferred_cities", current["preferred_cities"]), "preferred_cities"),
            "excluded_companies": _string_list(payload.get("excluded_companies", current["excluded_companies"]), "excluded_companies"),
            "preferences": preferences,
            "skills": _string_list(payload.get("skills", current["skills"]), "skills"),
            "current_resume_text": resume_text,
            "current_resume_parsed": parsed,
            "current_resume_filename": str(payload.get("current_resume_filename", current["current_resume_filename"]) or "").strip()[:255],
            "current_resume_sha256": hashlib.sha256(resume_text.encode("utf-8")).hexdigest() if resume_text else "",
            "resume_updated_at": current["resume_updated_at"],
        }
        resume_changed = any(
            values[name] != current[name]
            for name in ("current_resume_text", "current_resume_parsed", "current_resume_filename")
        )
        if resume_changed:
            values["resume_updated_at"] = utc_now()
        return self.repository.update(
            username=username,
            expected_version=expected_version,
            values=values,
        )
