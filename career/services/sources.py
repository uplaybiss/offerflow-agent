from __future__ import annotations

from typing import Any

from core.time import utc_now
from sources.adapters import SourceAdapterRegistry


UPDATABLE_SOURCE_FIELDS = {
    "company_name", "title", "location", "employment_type", "recruitment_cycle",
    "graduation_year", "deadline", "status", "description_text", "required_skills",
    "preferred_skills", "source_name", "source_url", "external_job_id",
    "company_career_url", "source_metadata",
}


class SourceRefreshService:
    def __init__(self, jobs: Any, registry: SourceAdapterRegistry) -> None:
        self.jobs = jobs
        self.registry = registry

    def capabilities(self) -> dict[str, Any]:
        return self.registry.capabilities()

    def preview(self, candidate_id: str, job_id: str) -> dict[str, Any]:
        job = self.jobs.get(candidate_id, job_id)
        base = {
            "job_id": job_id,
            "base_version": job["version"],
            "persisted": False,
            "job_unchanged": True,
            "checked_at": utc_now(),
        }
        if job["source_type"] != "COMPANY_CAREER":
            return {
                **base,
                "status": "NOT_APPLICABLE",
                "adapter_key": "",
                "update_preview": {},
                "message": "该岗位不是企业招聘官网来源，可继续手工维护",
            }
        metadata = job.get("source_metadata") if isinstance(job.get("source_metadata"), dict) else {}
        contract = metadata.get("source_contract") if isinstance(metadata.get("source_contract"), dict) else {}
        adapter_key = str(contract.get("adapter_key") or "").strip()
        adapter = self.registry.get(adapter_key)
        if not adapter:
            return {
                **base,
                "status": "UNAVAILABLE",
                "adapter_key": adapter_key,
                "update_preview": {},
                "message": "当前没有可用的企业官网适配器；岗位与投递核心功能不受影响",
            }
        try:
            raw = adapter.fetch_job(dict(job))
            if not isinstance(raw, dict):
                raise TypeError("adapter response must be an object")
            preview = {name: value for name, value in raw.items() if name in UPDATABLE_SOURCE_FIELDS}
            return {
                **base,
                "status": "PREVIEW",
                "adapter_key": adapter_key,
                "update_preview": preview,
                "message": "已生成单条岗位更新预览；请核对后通过岗位 PATCH 保存",
            }
        except Exception:
            return {
                **base,
                "status": "ERROR",
                "adapter_key": adapter_key,
                "update_preview": {},
                "message": "来源适配器暂时不可用；已保留原岗位数据，可继续手工维护",
            }
