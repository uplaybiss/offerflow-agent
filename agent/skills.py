from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

from core.errors import ValidationError


_ROOT = Path(__file__).resolve().parents[1] / "external-skills"
_COMMAND = re.compile(r"(?<!\S)/(job-match|great-resume)(?=\s|$)", re.IGNORECASE)


@dataclass(frozen=True)
class StaticSkill:
    name: str
    command: str
    prompt_path: Path
    allowed_tools: tuple[str, ...]
    required_tool: str
    default_request: str


@dataclass(frozen=True)
class SkillActivation:
    skill: StaticSkill
    message: str
    instructions: str


SKILLS = {
    "job-match": StaticSkill(
        name="job-match",
        command="/job-match",
        prompt_path=_ROOT / "job-match" / "SKILL.md",
        allowed_tools=(
            "get_candidate_360", "search_jobs", "get_job_detail",
            "analyze_job_match", "analyze_skill_gaps", "analyze_resume_for_job",
        ),
        required_tool="analyze_job_match",
        default_request="分析当前岗位与我的已确认事实是否匹配。",
    ),
    "great-resume": StaticSkill(
        name="great-resume",
        command="/great-resume",
        prompt_path=_ROOT / "great-resume" / "SKILL.md",
        allowed_tools=(
            "get_candidate_360", "search_jobs", "get_job_detail",
            "analyze_job_match", "analyze_resume_for_job",
        ),
        required_tool="analyze_resume_for_job",
        default_request="根据当前岗位和我的已确认事实提出简历修改建议。",
    ),
}


@lru_cache(maxsize=2)
def _instructions(name: str) -> str:
    return SKILLS[name].prompt_path.read_text(encoding="utf-8").strip()


def route_skill(message: str) -> SkillActivation | None:
    stripped = str(message or "").lstrip()
    first = _COMMAND.match(stripped)
    if first is None:
        return None
    commands = _COMMAND.findall(stripped)
    if len(commands) != 1:
        raise ValidationError("一次请求只能激活一个 Skill")
    skill = SKILLS[first.group(1).lower()]
    request = stripped[first.end():].strip() or skill.default_request
    return SkillActivation(skill=skill, message=request, instructions=_instructions(skill.name))


def scoped_tools(configured: list[str], activation: SkillActivation | None) -> list[str]:
    if activation is None:
        return list(configured)
    allowed = set(activation.skill.allowed_tools)
    effective = [name for name in configured if name in allowed]
    if activation.skill.required_tool not in effective:
        raise ValidationError(
            f"当前 AgentOps Tool whitelist 未开放 {activation.skill.required_tool}，无法执行 {activation.skill.command}"
        )
    return effective
