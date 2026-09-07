from __future__ import annotations

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
        selected_ids = list(dict.fromkeys(
            str(item or "").strip()
            for item in (job_ids or [])
            if str(item or "").strip()
        ))
        if len(selected_ids) > 20:
            raise ValidationError("技能缺口分析一次最多选择 20 个岗位")
        if selected_ids:
            jobs = [self.jobs.get(candidate["candidate_id"], job_id) for job_id in selected_ids]
        else:
            jobs = self.jobs.list(candidate["candidate_id"], favorite_only=favorite_only)[:20]

        grades: dict[str, int] = {}
        aggregates: dict[str, dict[str, Any]] = {}
        evidence: list[dict[str, Any]] = []
        for job in jobs:
            result = self.matching.evaluate(candidate, job)
            grades[result["grade"]] = grades.get(result["grade"], 0) + 1
            for requirement, coverage in (
                ("required", result["required_coverage"]),
                ("preferred", result["preferred_coverage"]),
            ):
                for skill in coverage["evidence"]:
                    canonical = skill["canonical_skill"]
                    aggregate = aggregates.setdefault(canonical, {
                        "canonical_skill": canonical,
                        "display_name": skill["job_skill"],
                        "category": skill["skill_category"],
                        "required_count": 0,
                        "preferred_count": 0,
                        "total_jobs": 0,
                        "candidate_has_skill": bool(skill["matched"]),
                        "variants": [],
                        "_job_ids": set(),
                    })
                    aggregate[f"{requirement}_count"] += 1
                    aggregate["candidate_has_skill"] = (
                        aggregate["candidate_has_skill"] or bool(skill["matched"])
                    )
                    aggregate["_job_ids"].add(job["job_id"])
                    if skill["job_skill"] not in aggregate["variants"]:
                        aggregate["variants"].append(skill["job_skill"])
            evidence.append({
                "job_id": job["job_id"],
                "company_name": job["company_name"],
                "title": job["title"],
                "grade": result["grade"],
                "hard_failures": [
                    item["name"] for item in result["hard_conditions"] if item["status"] == "FAIL"
                ],
                "required_missing": result["required_coverage"]["missing_skills"],
                "preferred_missing": result["preferred_coverage"]["missing_skills"],
            })

        skills: list[dict[str, Any]] = []
        for item in aggregates.values():
            item["total_jobs"] = len(item.pop("_job_ids"))
            item["variants"] = sorted(item["variants"], key=lambda value: value.casefold())
            skills.append(item)
        skills.sort(
            key=lambda item: (
                -item["total_jobs"], -item["required_count"], item["canonical_skill"]
            )
        )

        return {
            "scope": {
                "job_ids": [job["job_id"] for job in jobs],
                "favorite_only": bool(favorite_only),
            },
            "job_count": len(jobs),
            "grade_counts": grades,
            "frequency_threshold_jobs": 2,
            "skills": skills,
            "frequent_present": [
                item for item in skills
                if item["candidate_has_skill"] and item["total_jobs"] >= 2
            ],
            "frequent_missing_required": [
                item for item in skills
                if not item["candidate_has_skill"] and item["required_count"] >= 2
            ],
            "frequent_missing_preferred": [
                item for item in skills
                if not item["candidate_has_skill"] and item["preferred_count"] >= 2
            ],
            "low_frequency_missing": [
                item for item in skills
                if not item["candidate_has_skill"] and item["total_jobs"] == 1
            ],
            "evidence": evidence,
            "deterministic": True,
            "disclaimer": "仅按当前候选人技能与已保存岗位要求聚合，不代表录用概率。",
        }
