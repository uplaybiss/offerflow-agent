from __future__ import annotations

from collections import Counter
from typing import Any

from core.errors import ValidationError


class SkillGapService:
    def __init__(self, jobs: Any, matching: Any) -> None:
        self.jobs = jobs
        self.matching = matching

    def analyze(
        self,
        candidate: dict[str, Any],
        *,
        job_ids: list[str] | None = None,
        favorite_only: bool = False,
    ) -> dict[str, Any]:
        selected_ids = list(dict.fromkeys(str(item or "").strip() for item in (job_ids or []) if str(item or "").strip()))
        if len(selected_ids) > 20:
            raise ValidationError("技能缺口分析一次最多选择 20 个岗位")
        if selected_ids:
            jobs = [self.jobs.get(candidate["candidate_id"], job_id) for job_id in selected_ids]
        else:
            jobs = self.jobs.list(candidate["candidate_id"], favorite_only=favorite_only)[:20]
        required_missing: Counter[str] = Counter()
        preferred_missing: Counter[str] = Counter()
        grades: Counter[str] = Counter()
        evidence: list[dict[str, Any]] = []
        for job in jobs:
            result = self.matching.evaluate(candidate, job)
            grades[result["grade"]] += 1
            required_missing.update(result["required_coverage"]["missing_skills"])
            preferred_missing.update(result["preferred_coverage"]["missing_skills"])
            evidence.append({
                "job_id": job["job_id"],
                "company_name": job["company_name"],
                "title": job["title"],
                "grade": result["grade"],
                "hard_failures": [item["name"] for item in result["hard_conditions"] if item["status"] == "FAIL"],
                "required_missing": result["required_coverage"]["missing_skills"],
                "preferred_missing": result["preferred_coverage"]["missing_skills"],
            })
        return {
            "scope": {"job_ids": [job["job_id"] for job in jobs], "favorite_only": bool(favorite_only)},
            "job_count": len(jobs),
            "grade_counts": dict(grades),
            "required_priorities": [
                {"skill": skill, "missing_in_jobs": count, "priority": "P1" if count >= 2 else "P2"}
                for skill, count in required_missing.most_common()
            ],
            "preferred_priorities": [
                {"skill": skill, "missing_in_jobs": count, "priority": "P2" if count >= 2 else "P3"}
                for skill, count in preferred_missing.most_common()
            ],
            "evidence": evidence,
            "deterministic": True,
            "disclaimer": "仅按当前候选人技能与已保存岗位要求聚合，不代表录用概率。",
        }
