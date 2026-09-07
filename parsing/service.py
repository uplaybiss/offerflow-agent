from __future__ import annotations

from datetime import date
from typing import Any

from core.errors import ValidationError
from parsing.extractors import extract_resume
from parsing.llm import LlmClient, require_text


RESUME_INSTRUCTIONS = """
输出键：full_name,email,phone,graduation_year,degree,target_roles,preferred_cities,skills,
education,experience,projects,certifications,languages,summary,extraction_notes。
字符串未知时输出空字符串；数组未知时输出空数组。skills 必须是原文出现的具体技术名词，
不要把 FastAPI 改写成 Python Web，也不要推测求职城市或目标岗位。
""".strip()

JD_INSTRUCTIONS = """
输出键：company_name,title,location,employment_type,recruitment_cycle,graduation_year,deadline,
required_skills,preferred_skills,hard_conditions,extraction_notes。
deadline 仅在原文有明确日期时输出 YYYY-MM-DD，否则空字符串。
hard_conditions 必须是对象，仅允许 required_degree,required_languages,visa_sponsorship,remote_supported；
布尔值未知时为 null。required_skills 和 preferred_skills 保留具体、原子化技能名，
不要用技能大类替换具体框架，不要把职责自动当作硬性要求。
""".strip()


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:200])
    return result


def _records(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)][:100] if isinstance(value, list) else []


class ParsingService:
    def __init__(self, llm: LlmClient) -> None:
        self.llm = llm

    def capabilities(self) -> dict[str, Any]:
        return {
            "resume_file_types": ["txt", "pdf"],
            "max_resume_bytes": 5 * 1024 * 1024,
            "llm_available": self.llm.available,
            "llm_provider": self.llm.provider,
            "llm_model": self.llm.model,
            "preview_persistence": "browser_only_until_confirmed",
        }

    def extract_resume(self, filename: str, content: bytes) -> dict[str, Any]:
        return extract_resume(filename, content)

    def resume_preview(self, text: str) -> dict[str, Any]:
        original = require_text(text, "简历文本")
        raw = self.llm.complete_json(
            task="解析当前简历并生成待用户校对的结构化预览",
            instructions=RESUME_INSTRUCTIONS,
            input_text=original,
        )
        preview = {
            "full_name": str(raw.get("full_name") or "").strip()[:100],
            "email": str(raw.get("email") or "").strip()[:200],
            "phone": str(raw.get("phone") or "").strip()[:50],
            "graduation_year": str(raw.get("graduation_year") or "").strip()[:20],
            "degree": str(raw.get("degree") or "").strip()[:100],
            "target_roles": _strings(raw.get("target_roles")),
            "preferred_cities": _strings(raw.get("preferred_cities")),
            "skills": _strings(raw.get("skills")),
            "current_resume_parsed": {
                "education": _records(raw.get("education")),
                "experience": _records(raw.get("experience")),
                "projects": _records(raw.get("projects")),
                "certifications": _strings(raw.get("certifications")),
                "languages": _strings(raw.get("languages")),
                "summary": str(raw.get("summary") or "").strip()[:2_000],
                "extraction_notes": _strings(raw.get("extraction_notes")),
                "parser": {"provider": self.llm.provider, "model": self.llm.model, "schema": "resume_preview_v1"},
            },
        }
        return {"preview": preview, "persisted": False, "requires_confirmation": True}

    def jd_preview(self, text: str) -> dict[str, Any]:
        original = require_text(text, "JD 文本")
        raw = self.llm.complete_json(
            task="解析招聘 JD 并生成待用户校对的结构化预览",
            instructions=JD_INSTRUCTIONS,
            input_text=original,
        )
        deadline = str(raw.get("deadline") or "").strip()
        if deadline:
            try:
                date.fromisoformat(deadline)
            except ValueError:
                deadline = ""
        hard = raw.get("hard_conditions") if isinstance(raw.get("hard_conditions"), dict) else {}
        hard_conditions = {
            "required_degree": str(hard.get("required_degree") or "").strip()[:100],
            "required_languages": _strings(hard.get("required_languages")),
            "visa_sponsorship": hard.get("visa_sponsorship") if isinstance(hard.get("visa_sponsorship"), bool) else None,
            "remote_supported": hard.get("remote_supported") if isinstance(hard.get("remote_supported"), bool) else None,
        }
        preview = {
            "company_name": str(raw.get("company_name") or "").strip()[:200],
            "title": str(raw.get("title") or "").strip()[:200],
            "location": str(raw.get("location") or "").strip()[:200],
            "employment_type": str(raw.get("employment_type") or "").strip()[:100],
            "recruitment_cycle": str(raw.get("recruitment_cycle") or "").strip()[:100],
            "graduation_year": str(raw.get("graduation_year") or "").strip()[:20],
            "deadline": deadline,
            "required_skills": _strings(raw.get("required_skills")),
            "preferred_skills": _strings(raw.get("preferred_skills")),
            "hard_conditions": hard_conditions,
            "extraction_notes": _strings(raw.get("extraction_notes")),
            "parser": {"provider": self.llm.provider, "model": self.llm.model, "schema": "jd_preview_v1"},
        }
        return {"preview": preview, "persisted": False, "requires_confirmation": True}
