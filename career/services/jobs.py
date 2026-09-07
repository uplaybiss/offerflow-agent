from __future__ import annotations

import hashlib
from datetime import date
from typing import Any

from career.models import JobStatus, SourceType
from career.repositories.jobs import JobRepository
from core.database import json_dump
from core.errors import ValidationError
from core.time import local_today_iso, utc_now


def _enum(value: Any, enum_type: type, field: str) -> str:
    normalized = str(value or "").upper()
    allowed = {item.value for item in enum_type}
    if normalized not in allowed:
        raise ValidationError(f"{field} 无效")
    return normalized


def _skill_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValidationError(f"{field} 必须是数组")
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _checksum(values: dict[str, Any]) -> str:
    canonical = "\n".join(
        str(values.get(name, "")).strip().lower()
        for name in ("company_name", "title", "location", "description_text", "external_job_id")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class JobService:
    def __init__(self, repository: JobRepository) -> None:
        self.repository = repository

    def _validate(self, payload: dict[str, Any], current: dict[str, Any] | None = None) -> dict[str, Any]:
        current = current or {}
        value = lambda name, default="": payload.get(name, current.get(name, default))
        company = str(value("company_name") or "").strip()
        title = str(value("title") or "").strip()
        if not company or not title:
            raise ValidationError("公司名称和岗位名称不能为空")
        status = _enum(value("status", JobStatus.ACTIVE.value), JobStatus, "status")
        source_type = _enum(value("source_type", SourceType.MANUAL.value), SourceType, "source_type")
        metadata = value("source_metadata", {})
        if not isinstance(metadata, dict):
            raise ValidationError("source_metadata 必须是 JSON 对象")
        deadline = str(value("deadline") or "").strip()
        if deadline:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                raise ValidationError("deadline 必须是 YYYY-MM-DD") from None
        values = {
            "company_name": company[:200],
            "title": title[:200],
            "location": str(value("location") or "").strip()[:200],
            "employment_type": str(value("employment_type") or "").strip()[:100],
            "recruitment_cycle": str(value("recruitment_cycle") or "").strip()[:100],
            "graduation_year": str(value("graduation_year") or "").strip()[:20],
            "deadline": deadline,
            "status": status,
            "description_text": str(value("description_text") or "")[:500_000],
            "required_skills": _skill_list(value("required_skills", []), "required_skills"),
            "preferred_skills": _skill_list(value("preferred_skills", []), "preferred_skills"),
            "is_favorite": bool(value("is_favorite", False)),
            "source_type": source_type,
            "source_name": str(value("source_name") or "").strip()[:200],
            "source_url": str(value("source_url") or "").strip()[:2000],
            "external_job_id": str(value("external_job_id") or "").strip()[:200],
            "company_career_url": str(value("company_career_url") or "").strip()[:2000],
            "source_metadata": metadata,
        }
        values["content_sha256"] = _checksum(values)
        return values

    @staticmethod
    def _present(job: dict[str, Any]) -> dict[str, Any]:
        result = dict(job)
        result["effective_status"] = (
            JobStatus.EXPIRED.value
            if job["status"] == JobStatus.ACTIVE.value
            and job["deadline"]
            and job["deadline"] < local_today_iso()
            else job["status"]
        )
        return result

    def create(self, candidate_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._present(self.repository.create(candidate_id=candidate_id, values=self._validate(payload)))

    def get(self, candidate_id: str, job_id: str) -> dict[str, Any]:
        return self._present(self.repository.get(candidate_id=candidate_id, job_id=job_id))

    def list(self, candidate_id: str, *, search: str = "", status: str = "", favorite_only: bool = False) -> list[dict[str, Any]]:
        if status:
            _enum(status, JobStatus, "status")
        return [
            self._present(item)
            for item in self.repository.list(
                candidate_id=candidate_id,
                search=str(search or "").strip(),
                status=str(status or "").upper(),
                as_of_date=local_today_iso(),
                favorite_only=favorite_only,
            )
        ]

    def update(self, candidate_id: str, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.repository.get(candidate_id=candidate_id, job_id=job_id)
        try:
            expected_version = int(payload.get("version"))
        except (TypeError, ValueError):
            raise ValidationError("version 必须是整数") from None
        validated = self._validate(payload, current)
        if validated["is_favorite"] == current["is_favorite"]:
            favorited_at = current["favorited_at"]
        else:
            favorited_at = utc_now() if validated["is_favorite"] else ""
        changes = {
            "company_name": validated["company_name"],
            "title": validated["title"],
            "location": validated["location"],
            "employment_type": validated["employment_type"],
            "recruitment_cycle": validated["recruitment_cycle"],
            "graduation_year": validated["graduation_year"],
            "deadline": validated["deadline"],
            "status": validated["status"],
            "description_text": validated["description_text"],
            "required_skills_json": json_dump(validated["required_skills"]),
            "preferred_skills_json": json_dump(validated["preferred_skills"]),
            "is_favorite": 1 if validated["is_favorite"] else 0,
            "favorited_at": favorited_at,
            "source_type": validated["source_type"],
            "source_name": validated["source_name"],
            "source_url": validated["source_url"],
            "external_job_id": validated["external_job_id"],
            "company_career_url": validated["company_career_url"],
            "source_metadata_json": json_dump(validated["source_metadata"]),
            "content_sha256": validated["content_sha256"],
            "last_seen_at": utc_now(),
        }
        return self._present(
            self.repository.update(
                candidate_id=candidate_id,
                job_id=job_id,
                expected_version=expected_version,
                changes=changes,
            )
        )
