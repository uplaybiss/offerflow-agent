from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from career.services.jobs import JobService
from core.errors import ValidationError
from matching.dictionary import DICTIONARY_VERSION, SkillDictionary
from parsing.llm import LlmClient


DISCLAIMER = "启发式规则，非录用概率或统计标准"


def _ratio(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return min(1.0, max(0.0, value))


def _text_set(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item or "").strip() for item in value if str(item or "").strip()))


def _normalized_text(value: Any) -> str:
    return re.sub(r"[\s,，。._\-（）()]+", "", str(value or "").casefold())


def _years(value: Any) -> set[str]:
    return set(re.findall(r"20\d{2}", str(value or "")))


def _degree_rank(value: Any) -> int | None:
    text = str(value or "").casefold()
    for words, rank in (
        (("phd", "doctor", "博士"), 4),
        (("master", "msc", "硕士", "研究生"), 3),
        (("bachelor", "本科", "学士"), 2),
        (("associate", "大专", "专科"), 1),
    ):
        if any(word in text for word in words):
            return rank
    return None


class MatchingService:
    def __init__(self, jobs: JobService, dictionary: SkillDictionary, llm: LlmClient) -> None:
        self.jobs = jobs
        self.dictionary = dictionary
        self.llm = llm

    def config(self) -> dict[str, Any]:
        match = _ratio("MATCH_REQUIRED_COVERAGE", 0.60)
        strong = max(match, _ratio("MATCH_STRONG_REQUIRED_COVERAGE", 0.80))
        return {
            "version": os.getenv("MATCH_HEURISTIC_VERSION", "heuristic_v1") or "heuristic_v1",
            "strong_required_coverage": strong,
            "match_required_coverage": match,
            "disclaimer": DISCLAIMER,
            "skill_dictionary": self.dictionary.summary(),
        }

    @staticmethod
    def _check(name: str, status: str, actual: Any, expected: Any, evidence: str) -> dict[str, Any]:
        return {"name": name, "status": status, "actual": actual, "expected": expected, "evidence": evidence}

    def _hard_conditions(self, candidate: dict[str, Any], job: dict[str, Any]) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        expired = job["effective_status"] == "EXPIRED"
        checks.append(self._check(
            "deadline", "FAIL" if expired else ("UNKNOWN" if not job["deadline"] else "PASS"),
            job["deadline"] or None, "not expired", "岗位有效状态由 Job 状态和配置时区下的截止日期确定",
        ))

        candidate_years = _years(candidate.get("graduation_year"))
        job_years = _years(job.get("graduation_year"))
        if candidate_years and job_years:
            passed = bool(candidate_years & job_years)
            checks.append(self._check("graduation_year", "PASS" if passed else "FAIL", sorted(candidate_years), sorted(job_years), "仅比较双方明确出现的毕业年份"))
        else:
            checks.append(self._check("graduation_year", "UNKNOWN", sorted(candidate_years) or None, sorted(job_years) or None, "候选人或岗位未提供明确毕业年份"))

        excluded = _text_set(candidate.get("excluded_companies"))
        company = _normalized_text(job.get("company_name"))
        blocked = next((item for item in excluded if _normalized_text(item) and (_normalized_text(item) in company or company in _normalized_text(item))), "")
        checks.append(self._check("excluded_company", "FAIL" if blocked else "PASS", job.get("company_name"), excluded, f"命中排除公司：{blocked}" if blocked else "未命中候选人排除公司清单"))

        preferred_cities = _text_set(candidate.get("preferred_cities"))
        job_location = _normalized_text(job.get("location"))
        metadata = job.get("source_metadata") if isinstance(job.get("source_metadata"), dict) else {}
        phase2 = metadata.get("phase2_parsed") if isinstance(metadata.get("phase2_parsed"), dict) else {}
        hard = phase2.get("hard_conditions") if isinstance(phase2.get("hard_conditions"), dict) else {}
        remote_supported = hard.get("remote_supported") is True or any(word in job_location for word in ("远程", "remote"))
        unrestricted = any(_normalized_text(city) in {"不限", "全国", "remote", "远程"} for city in preferred_cities)
        city_hit = any(_normalized_text(city) and _normalized_text(city) in job_location for city in preferred_cities)
        if preferred_cities and job_location:
            location_pass = remote_supported or unrestricted or city_hit
            checks.append(self._check("location", "PASS" if location_pass else "FAIL", job.get("location"), preferred_cities, "明确支持远程或岗位地点命中接受城市" if location_pass else "岗位地点未命中候选人接受城市且未明确支持远程"))
        else:
            checks.append(self._check("location", "UNKNOWN", job.get("location") or None, preferred_cities or None, "候选人或岗位未提供明确地点约束"))

        preferences = candidate.get("preferences") if isinstance(candidate.get("preferences"), dict) else {}
        accepted_types = _text_set(preferences.get("accepted_employment_types"))
        excluded_types = _text_set(preferences.get("excluded_employment_types"))
        employment = _normalized_text(job.get("employment_type"))
        type_blocked = next((item for item in excluded_types if _normalized_text(item) == employment), "")
        type_allowed = not accepted_types or any(_normalized_text(item) == employment for item in accepted_types)
        if employment and (accepted_types or excluded_types):
            checks.append(self._check("employment_type", "FAIL" if type_blocked or not type_allowed else "PASS", job.get("employment_type"), {"accepted": accepted_types, "excluded": excluded_types}, "按候选人显式岗位类型偏好比较"))
        else:
            checks.append(self._check("employment_type", "UNKNOWN", job.get("employment_type") or None, None, "未配置双方可比较的岗位类型约束"))

        required_degree = hard.get("required_degree")
        required_rank = _degree_rank(required_degree)
        candidate_rank = _degree_rank(candidate.get("degree"))
        if required_rank and candidate_rank:
            checks.append(self._check("degree", "PASS" if candidate_rank >= required_rank else "FAIL", candidate.get("degree"), required_degree, "仅比较明确且可识别的学历层级"))
        else:
            checks.append(self._check("degree", "UNKNOWN", candidate.get("degree") or None, required_degree or None, "岗位或候选人缺少可确定的学历层级"))

        required_languages = _text_set(hard.get("required_languages"))
        candidate_languages = _text_set(preferences.get("languages"))
        if required_languages and candidate_languages:
            candidate_language_keys = {_normalized_text(item) for item in candidate_languages}
            missing_languages = [item for item in required_languages if _normalized_text(item) not in candidate_language_keys]
            checks.append(self._check("languages", "FAIL" if missing_languages else "PASS", candidate_languages, required_languages, f"明确缺少：{', '.join(missing_languages)}" if missing_languages else "明确语言要求均命中"))
        else:
            checks.append(self._check("languages", "UNKNOWN", candidate_languages or None, required_languages or None, "岗位或候选人未提供可比较的语言清单"))

        requires_visa = preferences.get("requires_visa")
        sponsorship = hard.get("visa_sponsorship")
        if isinstance(requires_visa, bool) and isinstance(sponsorship, bool):
            passed = not requires_visa or sponsorship
            checks.append(self._check("visa", "PASS" if passed else "FAIL", {"candidate_requires_visa": requires_visa}, {"visa_sponsorship": sponsorship}, "仅按双方明确布尔值判断"))
        else:
            checks.append(self._check("visa", "UNKNOWN", requires_visa, sponsorship, "签证需求或岗位支持信息不完整"))
        return checks

    def _skill_group(self, candidate_skills: list[str], job_skills: list[str]) -> dict[str, Any]:
        normalized_candidate = self.dictionary.normalize_many(candidate_skills)
        normalized_job = self.dictionary.normalize_many(job_skills)
        by_canonical = {item["canonical_skill"]: item for item in normalized_candidate}
        evidence: list[dict[str, Any]] = []
        for item in normalized_job:
            candidate_item = by_canonical.get(item["canonical_skill"])
            evidence.append({
                "job_skill": item["raw_skill"],
                "candidate_skill": candidate_item["raw_skill"] if candidate_item else None,
                "canonical_skill": item["canonical_skill"],
                "skill_category": item["skill_category"],
                "matched": candidate_item is not None,
                "match_rule": "canonical_exact_or_alias_v1" if candidate_item else "no_canonical_match",
            })
        matched = [item for item in evidence if item["matched"]]
        missing = [item for item in evidence if not item["matched"]]
        total = len(evidence)
        return {
            "matched": len(matched), "total": total,
            "ratio": round(len(matched) / total, 4) if total else None,
            "evidence": evidence,
            "matched_skills": [item["job_skill"] for item in matched],
            "missing_skills": [item["job_skill"] for item in missing],
        }

    def evaluate(self, candidate: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
        config = self.config()
        hard_conditions = self._hard_conditions(candidate, job)
        required = self._skill_group(_text_set(candidate.get("skills")), _text_set(job.get("required_skills")))
        preferred = self._skill_group(_text_set(candidate.get("skills")), _text_set(job.get("preferred_skills")))
        metadata = job.get("source_metadata") if isinstance(job.get("source_metadata"), dict) else {}
        phase2 = metadata.get("phase2_parsed") if isinstance(metadata.get("phase2_parsed"), dict) else {}
        critical_raw = _text_set(phase2.get("critical_required_skills"))
        critical_canonical = {item["canonical_skill"] for item in self.dictionary.normalize_many(critical_raw)}
        critical_gaps = [item for item in required["evidence"] if not item["matched"] and item["canonical_skill"] in critical_canonical]
        hard_failed = any(item["status"] == "FAIL" for item in hard_conditions)
        if hard_failed:
            grade = "NOT_RECOMMENDED"
        elif required["ratio"] is None or critical_gaps:
            grade = "WEAK_MATCH"
        elif required["ratio"] >= config["strong_required_coverage"]:
            grade = "STRONG_MATCH"
        elif required["ratio"] >= config["match_required_coverage"]:
            grade = "MATCH"
        else:
            grade = "WEAK_MATCH"
        result: dict[str, Any] = {
            "heuristic": config,
            "candidate": {"candidate_id": candidate["candidate_id"], "version": candidate["version"]},
            "job": {"job_id": job["job_id"], "version": job["version"], "company_name": job["company_name"], "title": job["title"]},
            "grade": grade,
            "hard_conditions": hard_conditions,
            "required_coverage": required,
            "preferred_coverage": preferred,
            "critical_gaps": [item["job_skill"] for item in critical_gaps],
            "other_gaps": [item for item in required["missing_skills"] if item not in {gap["job_skill"] for gap in critical_gaps}],
            "deterministic": True,
            "llm_decided": False,
        }
        result["result_fingerprint"] = hashlib.sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return result

    def match_job(self, candidate: dict[str, Any], job_id: str) -> dict[str, Any]:
        job = self.jobs.get(candidate["candidate_id"], job_id)
        return self.evaluate(candidate, job)

    def compare(self, candidate: dict[str, Any], job_ids: Any) -> dict[str, Any]:
        if not isinstance(job_ids, list):
            raise ValidationError("job_ids 必须是数组")
        unique_ids = list(dict.fromkeys(str(item or "").strip() for item in job_ids if str(item or "").strip()))
        if len(unique_ids) < 2 or len(unique_ids) > 4:
            raise ValidationError("岗位对比一次需选择 2-4 个不同岗位")
        items = []
        for job_id in unique_ids:
            job = self.jobs.get(candidate["candidate_id"], job_id)
            items.append({"job": job, "match": self.evaluate(candidate, job)})
        return {
            "heuristic": self.config(),
            "items": items,
            "deterministic": True,
        }

    def explain(self, result: dict[str, Any]) -> dict[str, Any]:
        if not result.get("deterministic") or not result.get("result_fingerprint"):
            raise ValidationError("缺少确定性匹配事实")
        facts = {
            "grade": result["grade"],
            "hard_conditions": result["hard_conditions"],
            "required_coverage": result["required_coverage"],
            "preferred_coverage": result["preferred_coverage"],
            "critical_gaps": result["critical_gaps"],
            "other_gaps": result["other_gaps"],
            "disclaimer": DISCLAIMER,
        }
        explanation = self.llm.complete_text(
            task="用简洁中文解释该岗位与候选人的匹配点、硬条件和具体缺口",
            instructions="先说硬条件，再说已命中技能和缺口；不得输出概率或新增事实。",
            facts=facts,
        )
        return {"explanation": explanation, "result_fingerprint": result["result_fingerprint"], "facts_unchanged": True}
