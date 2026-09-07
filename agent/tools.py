from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import json
from typing import Any, Callable

from langchain_core.tools import tool

from agent.context import current_agent_context
from core.errors import ValidationError


TOOLSET_VERSION = "career-tools-v1"
TOOL_RISKS = {
    "get_candidate_360": "READ_ONLY",
    "search_jobs": "READ_ONLY",
    "get_job_detail": "READ_ONLY",
    "analyze_job_match": "READ_ONLY",
    "compare_jobs": "READ_ONLY",
    "analyze_skill_gaps": "READ_ONLY",
    "query_applications": "READ_ONLY",
    "list_upcoming_tasks": "READ_ONLY",
    "propose_application_change": "CONTROLLED_WRITE",
    "confirm_application_change": "CONFIRMATION_WRITE",
}


def _trace_tool(name: str) -> Callable[[Callable[..., dict[str, Any]]], Callable[..., dict[str, Any]]]:
    def decorate(function: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> dict[str, Any]:
            context = current_agent_context()
            refs = {
                key: kwargs[key]
                for key in ("job_id", "job_ids", "application_id", "action_id", "expected_version", "target_status", "current_round_id", "action_type")
                if key in kwargs
            }
            started, started_at = context.trace.tool_start(name, TOOL_RISKS[name], refs)
            try:
                result = function(*args, **kwargs)
            except Exception as exc:
                context.trace.tool_end(
                    name, TOOL_RISKS[name], started, started_at,
                    status="ERROR", reason_code=getattr(exc, "code", exc.__class__.__name__), business_refs=refs,
                )
                raise
            output_refs = dict(refs)
            output_refs.update({key: result[key] for key in ("action_id", "application_id", "from_status", "to_status", "resulting_version", "grade") if key in result})
            blocked = bool(result.get("blocked"))
            context.trace.tool_end(
                name, TOOL_RISKS[name], started, started_at,
                status="BLOCKED" if blocked else "SUCCESS",
                reason_code="CONFIRMATION_REQUIRED" if blocked else "",
                business_refs=output_refs,
                metrics={
                    "item_count": result.get("item_count", result.get("job_count", 0)),
                    "matched_count": result.get("matched_count", 0),
                    "missing_count": result.get("missing_count", 0),
                },
            )
            return result
        return wrapped
    return decorate


@tool
@_trace_tool("get_candidate_360")
def get_candidate_360() -> dict[str, Any]:
    """获取当前登录候选人的裁剪档案、偏好、技能、近期任务和活对象引用；不返回姓名、联系方式或简历原文。"""
    context = current_agent_context()
    candidate = context.candidate
    applications = context.services.applications.list(candidate["candidate_id"])
    tasks = context.services.tasks.list(candidate["candidate_id"])
    interviews = context.services.interviews.list(candidate["candidate_id"], upcoming_only=True)
    return {
        "candidate": {
            "candidate_id": candidate["candidate_id"],
            "graduation_year": candidate["graduation_year"],
            "degree": candidate["degree"],
            "target_roles": candidate["target_roles"],
            "preferred_cities": candidate["preferred_cities"],
            "excluded_companies": candidate["excluded_companies"],
            "preferences": candidate["preferences"],
            "skills": candidate["skills"],
            "profile_version": candidate["version"],
        },
        "current_refs": {
            "job_id": context.current_job_id,
            "application_id": context.current_application_id,
            "interview_id": context.current_interview_id,
            "task_id": context.current_task_id,
        },
        "counts": {
            "applications": len(applications),
            "open_tasks": sum(item["status"] in {"TODO", "IN_PROGRESS"} for item in tasks),
            "upcoming_interviews": len(interviews),
        },
        "item_count": len(applications) + len(tasks) + len(interviews),
    }


@tool
@_trace_tool("search_jobs")
def search_jobs(
    query: str = "",
    status: str = "",
    favorite_only: bool = False,
    not_applied_only: bool = False,
    deadline_from: str = "",
    deadline_to: str = "",
) -> dict[str, Any]:
    """按公司、岗位、地点、有效状态、收藏、是否未投递和截止日期检索当前候选人的岗位。"""
    context = current_agent_context()
    candidate_id = context.candidate["candidate_id"]
    jobs = context.services.jobs.list(candidate_id, search=query, status=status, favorite_only=favorite_only)
    if not_applied_only:
        applied_job_ids = {item["job_id"] for item in context.services.applications.list(candidate_id)}
        jobs = [item for item in jobs if item["job_id"] not in applied_job_ids]
    if deadline_from:
        jobs = [item for item in jobs if item["deadline"] and item["deadline"] >= deadline_from]
    if deadline_to:
        jobs = [item for item in jobs if item["deadline"] and item["deadline"] <= deadline_to]
    items = [
        {
            "job_id": item["job_id"], "company_name": item["company_name"], "title": item["title"],
            "location": item["location"], "deadline": item["deadline"], "status": item["effective_status"],
            "is_favorite": item["is_favorite"], "required_skills": item["required_skills"],
            "preferred_skills": item["preferred_skills"], "version": item["version"],
        }
        for item in jobs[:50]
    ]
    return {"items": items, "item_count": len(items)}


@tool
@_trace_tool("get_job_detail")
def get_job_detail(job_id: str) -> dict[str, Any]:
    """获取当前候选人的一个结构化岗位详情和来源信息。"""
    context = current_agent_context()
    job = context.services.jobs.get(context.candidate["candidate_id"], job_id)
    return {"job": {key: value for key, value in job.items() if key != "candidate_id"}, "job_id": job_id, "item_count": 1}


@tool
@_trace_tool("analyze_job_match")
def analyze_job_match(job_id: str) -> dict[str, Any]:
    """用确定性 heuristic_v1 计算岗位硬条件、required/preferred skill coverage、等级和具体缺口。"""
    context = current_agent_context()
    result = context.services.matching.match_job(context.candidate, job_id)
    safe_result = {key: value for key, value in result.items() if key != "candidate"}
    return {
        "match": safe_result,
        "job_id": job_id,
        "grade": result["grade"],
        "matched_count": result["required_coverage"]["matched"],
        "missing_count": len(result["required_coverage"]["missing_skills"]),
    }


@tool
@_trace_tool("compare_jobs")
def compare_jobs(job_ids: list[str]) -> dict[str, Any]:
    """按同一确定性规则比较 2-5 个当前候选人的岗位。"""
    context = current_agent_context()
    unique_ids = list(dict.fromkeys(str(item or "").strip() for item in job_ids if str(item or "").strip()))
    if len(unique_ids) < 2 or len(unique_ids) > 5:
        raise ValidationError("Career Agent 岗位对比一次需选择 2-5 个不同岗位")
    items = []
    for job_id in unique_ids:
        job = context.services.jobs.get(context.candidate["candidate_id"], job_id)
        safe_job = {key: value for key, value in job.items() if key != "candidate_id"}
        match = context.services.matching.evaluate(context.candidate, job)
        safe_match = {key: value for key, value in match.items() if key != "candidate"}
        items.append({"job": safe_job, "match": safe_match})
    comparison = {
        "heuristic": context.services.matching.config(),
        "items": items,
        "deterministic": True,
    }
    return {"comparison": comparison, "job_ids": unique_ids, "item_count": len(comparison["items"])}


@tool
@_trace_tool("analyze_skill_gaps")
def analyze_skill_gaps(job_ids: list[str] | None = None, favorite_only: bool = True) -> dict[str, Any]:
    """聚合选定岗位或收藏岗位的真实技能缺口并给出学习优先级，不虚构候选人已掌握技能。"""
    context = current_agent_context()
    return context.services.skill_gaps.analyze(context.candidate, job_ids=job_ids, favorite_only=favorite_only)


@tool
@_trace_tool("query_applications")
def query_applications(status: str = "", include_timeline: bool = False) -> dict[str, Any]:
    """查询当前候选人的投递状态；可按状态过滤并按需返回状态事件时间线。"""
    context = current_agent_context()
    candidate_id = context.candidate["candidate_id"]
    items = context.services.applications.list(candidate_id, status)
    if include_timeline:
        items = [context.services.applications.get(candidate_id, item["application_id"]) for item in items[:50]]
    else:
        items = items[:50]
    return {"items": items, "item_count": len(items)}


@tool
@_trace_tool("list_upcoming_tasks")
def list_upcoming_tasks(days: int = 7, status: str = "") -> dict[str, Any]:
    """查询当前候选人未来若干天的待办、材料、测评和面试任务。"""
    context = current_agent_context()
    try:
        days = max(1, min(int(days), 365))
    except (TypeError, ValueError):
        raise ValidationError("days 必须是整数") from None
    now = datetime.now(timezone.utc)
    limit = now + timedelta(days=days)
    items = context.services.tasks.list(context.candidate["candidate_id"], status)
    filtered = []
    for item in items:
        if item["status"] not in {"TODO", "IN_PROGRESS"} or not item["due_at"]:
            continue
        due = datetime.fromisoformat(item["due_at"][:-1] + "+00:00" if item["due_at"].endswith("Z") else item["due_at"])
        if now <= due.astimezone(timezone.utc) <= limit:
            filtered.append(item)
    return {"items": filtered[:50], "item_count": len(filtered[:50]), "days": days}


@tool
@_trace_tool("propose_application_change")
def propose_application_change(
    application_id: str,
    expected_version: int,
    target_status: str = "",
    action_type: str = "APPLICATION_TRANSITION",
    next_action: str = "",
    notes: str = "",
    current_round_id: str = "",
    current_round_result: str = "",
    next_round_type: str = "OTHER",
    next_round_title: str = "",
    next_round_scheduled_at: str = "",
    task_title: str = "",
    task_due_at: str = "",
    expected_interview_version: int = 0,
) -> dict[str, Any]:
    """创建投递状态或面试推进确认卡；不直接写业务数据，用户必须在界面显式确认。"""
    context = current_agent_context()
    normalized_type = str(action_type or "APPLICATION_TRANSITION").upper()
    if context.sandbox:
        return {
            "sandbox": True, "requires_confirmation": True, "persisted": False,
            "application_id": application_id, "to_status": target_status,
            "expected_version": expected_version, "action_id": "SANDBOX-ACTION",
            "action_type": normalized_type,
        }
    if normalized_type == "APPLICATION_TRANSITION":
        result = context.services.pending_actions.propose_application_transition(
            candidate_id=context.candidate["candidate_id"],
            actor_username=context.actor_username,
            chat_id=context.chat_id,
            application_id=application_id,
            target_status=target_status,
            expected_version=expected_version,
            next_action=next_action,
            notes=notes,
        )
    elif normalized_type == "INTERVIEW_PROGRESSION":
        result = context.services.pending_actions.propose_interview_progression(
            candidate_id=context.candidate["candidate_id"],
            actor_username=context.actor_username,
            chat_id=context.chat_id,
            application_id=application_id,
            current_round_id=current_round_id,
            current_round_result=current_round_result,
            next_round_type=next_round_type,
            next_round_title=next_round_title,
            next_round_scheduled_at=next_round_scheduled_at,
            task_title=task_title,
            task_due_at=task_due_at,
            expected_application_version=expected_version,
            expected_interview_version=expected_interview_version,
        )
    else:
        raise ValidationError("action_type 必须是 APPLICATION_TRANSITION 或 INTERVIEW_PROGRESSION")
    action = result["action"]
    context.proposed_actions.append(action)
    return {
        "action_id": action["action_id"], "application_id": application_id,
        "from_status": "", "to_status": target_status,
        "expected_version": expected_version, "requires_confirmation": True,
        "expires_at": action["expires_at"], "idempotent_replay": result["idempotent_replay"],
        "action_type": normalized_type,
    }


@tool
@_trace_tool("confirm_application_change")
def confirm_application_change(action_id: str) -> dict[str, Any]:
    """执行已由当前用户在前端确认的投递变更；模型自身调用或 approved 参数不能授权。"""
    context = current_agent_context()
    if context.sandbox:
        return {"sandbox": True, "persisted": False, "action_id": action_id}
    if not context.confirmation_grant:
        return {
            "action_id": action_id,
            "blocked": True,
            "persisted": False,
            "reason_code": "CONFIRMATION_REQUIRED",
            "message": "必须通过确认卡片的结构化第二次请求执行",
        }
    result = context.services.pending_actions.confirm_pending_action(
        candidate_id=context.candidate["candidate_id"],
        actor_username=context.actor_username,
        action_id=action_id,
        confirmation_grant=context.confirmation_grant,
    )
    action = result["action"]
    transition = action["result"]
    return {
        "action_id": action_id,
        "action_type": transition.get("action_type", action["action_type"]),
        "application_id": transition["application_id"],
        "from_status": transition["from_status"],
        "to_status": transition["to_status"],
        "resulting_version": transition["resulting_version"],
        "idempotent_replay": result["idempotent_replay"],
        "persisted": True,
        **{
            key: transition[key]
            for key in ("completed_round_id", "next_round_id", "task_id")
            if key in transition
        },
    }


CAREER_TOOLS = [
    get_candidate_360,
    search_jobs,
    get_job_detail,
    analyze_job_match,
    compare_jobs,
    analyze_skill_gaps,
    query_applications,
    list_upcoming_tasks,
    propose_application_change,
    confirm_application_change,
]

CAREER_TOOL_CATALOG = {item.name: item for item in CAREER_TOOLS}
CAREER_TOOL_NAMES = tuple(CAREER_TOOL_CATALOG)


def enabled_tools_sha256(names: list[str] | tuple[str, ...]) -> str:
    canonical = json.dumps(sorted(set(names)), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
