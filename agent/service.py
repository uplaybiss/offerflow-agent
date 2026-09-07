from __future__ import annotations

import os
import secrets
from typing import Any

from agent.context import AgentRequestContext, bind_agent_context
from agent.runner import AgentRunner, LangChainCareerAgentRunner, PROMPT_VERSION
from agent.skills import route_skill, scoped_tools
from agent.tools import TOOLSET_VERSION, confirm_application_change, enabled_tools_sha256
from career.services.memory import validate_chat_id
from core.errors import ExternalServiceError, OfferFlowError, ValidationError
from matching.service import DISCLAIMER
from quality.store import QualityStore
from quality.trace import TraceRecorder


class CareerAgentService:
    def __init__(
        self,
        services: Any,
        quality_store: QualityStore,
        agentops: Any,
        runner: AgentRunner | None = None,
    ) -> None:
        self.services = services
        self.quality_store = quality_store
        self.agentops = agentops
        self.runner = runner or LangChainCareerAgentRunner()

    def capabilities(self) -> dict[str, Any]:
        release = self.agentops.store.release_state()
        stable = self.agentops.store.get_configuration(release["stable_version_id"])
        return {
            "available": bool(self.runner.available),
            "provider": "dashscope",
            "model": stable["settings"]["model_name"],
            "prompt_version": PROMPT_VERSION,
            "toolset_version": TOOLSET_VERSION,
            "tool_count": len(stable["settings"]["enabled_tools"]),
            "enabled_tools": stable["settings"]["enabled_tools"],
            "stream_format": "application/x-ndjson",
            "confirmation_required_for_writes": True,
            "trace_policy": "pii_allowlist_v1",
            "stable_version_id": release["stable_version_id"],
            "canary_version_id": release["canary_version_id"],
            "canary_percent": release["canary_percent"],
            "release_generation": release["generation"],
        }

    @staticmethod
    def _history(value: Any) -> list[dict[str, str]]:
        if not isinstance(value, list):
            return []
        result: list[dict[str, str]] = []
        for item in value[-20:]:
            if not isinstance(item, dict) or item.get("role") not in {"user", "assistant"}:
                continue
            content = str(item.get("content") or "")[:8_000]
            if content:
                result.append({"role": str(item["role"]), "content": content})
        return result

    def _safe_refs(self, candidate_id: str, payload: dict[str, Any]) -> dict[str, str]:
        jobs = {item["job_id"]: item for item in self.services.jobs.list(candidate_id)}
        applications = {
            item["application_id"]: item for item in self.services.applications.list(candidate_id)
        }
        interviews = {
            item["round_id"]: item for item in self.services.interviews.list(candidate_id)
        }
        tasks = {item["task_id"]: item for item in self.services.tasks.list(candidate_id)}
        refs = {
            "current_job_id": str(payload.get("current_job_id") or ""),
            "current_application_id": str(payload.get("current_application_id") or ""),
            "current_interview_id": str(payload.get("current_interview_id") or ""),
            "current_task_id": str(payload.get("current_task_id") or ""),
        }
        if refs["current_job_id"] not in jobs:
            refs["current_job_id"] = ""
        application = applications.get(refs["current_application_id"])
        if not application:
            refs["current_application_id"] = ""
        elif refs["current_job_id"] and application["job_id"] != refs["current_job_id"]:
            refs["current_job_id"] = application["job_id"]
        interview = interviews.get(refs["current_interview_id"])
        if not interview:
            refs["current_interview_id"] = ""
        elif refs["current_application_id"] and interview["application_id"] != refs["current_application_id"]:
            refs["current_interview_id"] = ""
        if refs["current_task_id"] not in tasks:
            refs["current_task_id"] = ""
        return refs

    def run(self, *, candidate: dict[str, Any], actor_username: str, payload: dict[str, Any], sandbox: bool = False, run_type: str = "CHAT") -> dict[str, Any]:
        message = str(payload.get("message") or "").strip()
        if not message:
            raise ValidationError("message 不能为空")
        if len(message) > 20_000:
            raise ValidationError("message 不能超过 20000 字符")
        activation = route_skill(message)
        chat_id = validate_chat_id(payload.get("chat_id"))
        if not self.runner.available and not sandbox:
            raise ExternalServiceError("Career Agent 未配置可用的 DASHSCOPE_API_KEY；其他页面仍可正常使用")
        runtime = self.agentops.select_configuration(f"{candidate['candidate_id']}:{chat_id}")
        settings = runtime["settings"]
        history_limit = int(settings["history_messages"])
        self.services.chats.ensure(candidate["candidate_id"], chat_id)
        history = self.services.chats.runner_history(
            candidate["candidate_id"], chat_id, history_limit
        )
        history_used = min(len(history), history_limit)
        configured_tools = [str(item) for item in settings["enabled_tools"]]
        enabled_tools = scoped_tools(configured_tools, activation)
        runner_settings = {
            **settings,
            "enabled_tools": enabled_tools,
            "_active_skill": activation.skill.name if activation else "",
            "_skill_prompt": activation.instructions if activation else "",
        }
        whitelist_hash = enabled_tools_sha256(enabled_tools)
        selected = self._safe_refs(candidate["candidate_id"], payload)
        self.services.chats.append(candidate["candidate_id"], chat_id, "USER", message)
        trace = TraceRecorder.start(
            self.quality_store,
            actor_username=actor_username,
            candidate_id=candidate["candidate_id"],
            chat_id=chat_id,
            run_type=run_type,
            model_name=str(settings["model_name"]),
            prompt_version=str(settings["prompt_version"]),
            toolset_version=str(settings["toolset_version"]),
            rule_version=str(settings["rule_version"]),
            input_chars=len(message),
            config_version_id=runtime["version_id"],
            release_channel=runtime["channel"],
            release_generation=runtime["generation"],
            enabled_tools_sha256=whitelist_hash,
            enabled_tool_count=len(enabled_tools),
            history_messages=history_limit,
            history_messages_used=history_used,
        )
        context = AgentRequestContext(
            services=self.services, candidate=candidate, actor_username=actor_username,
            chat_id=chat_id, trace=trace, sandbox=sandbox, **selected,
            active_skill=activation.skill.name if activation else "",
        )
        try:
            with bind_agent_context(context):
                output = self.runner.run(
                    message=activation.message if activation else message,
                    history=history,
                    runtime_config=runner_settings,
                )
            trace.mark_first_chunk()
            self.services.chats.append(
                candidate["candidate_id"], chat_id, "ASSISTANT", output.answer
            )
            memory = self.services.memory.remember(
                candidate["candidate_id"], chat_id, message=message,
                candidate_name=candidate.get("full_name", ""),
                current_job_id=context.current_job_id,
                current_application_id=context.current_application_id,
                current_interview_id=context.current_interview_id,
                current_task_id=context.current_task_id,
            )
            summary = trace.finish(
                status="SUCCESS", output_chars=len(output.answer),
                input_tokens=output.input_tokens, output_tokens=output.output_tokens,
            )
        except OfferFlowError:
            trace.finish(status="FAILED", output_chars=0)
            raise
        except Exception as exc:
            trace.finish(status="FAILED", output_chars=0)
            detail = str(exc)
            if "401" in detail or "unauthorized" in detail.casefold():
                raise ExternalServiceError("Career Agent 模型服务鉴权失败（401），请检查 DASHSCOPE_API_KEY") from exc
            if "403" in detail or "allocationquota" in detail.casefold() or "quota exhausted" in detail.casefold():
                raise ExternalServiceError("Career Agent 模型额度不可用（403），请检查 DashScope 额度或免费额度限制") from exc
            raise ExternalServiceError(f"Career Agent 模型调用失败（{exc.__class__.__name__}）") from exc
        return {
            "chat_id": chat_id,
            "answer": output.answer,
            "pending_actions": context.proposed_actions,
            "memory": memory,
            "trace": summary,
            "disclaimer": DISCLAIMER,
            "runtime": {
                "config_version_id": runtime["version_id"],
                "release_channel": runtime["channel"],
                "release_generation": runtime["generation"],
                "enabled_tools": enabled_tools,
                "enabled_tools_sha256": whitelist_hash,
                "enabled_tool_count": len(enabled_tools),
                "history_messages": history_limit,
                "history_messages_used": history_used,
                "active_skill": activation.skill.command if activation else "",
            },
        }

    def confirm_action(self, *, candidate: dict[str, Any], actor_username: str, action_id: str) -> dict[str, Any]:
        action = self.services.pending_actions.get(candidate["candidate_id"], action_id)
        runtime = self.agentops.select_configuration(f"{candidate['candidate_id']}:{action['chat_id']}")
        settings = runtime["settings"]
        enabled_tools = [str(item) for item in settings["enabled_tools"]]
        trace = TraceRecorder.start(
            self.quality_store,
            actor_username=actor_username,
            candidate_id=candidate["candidate_id"],
            chat_id=action["chat_id"],
            run_type="CHAT",
            model_name="server-confirmation",
            prompt_version=str(settings["prompt_version"]),
            toolset_version=str(settings["toolset_version"]),
            rule_version=str(settings["rule_version"]),
            input_chars=0,
            config_version_id=runtime["version_id"],
            release_channel=runtime["channel"],
            release_generation=runtime["generation"],
            enabled_tools_sha256=enabled_tools_sha256(enabled_tools),
            enabled_tool_count=len(enabled_tools),
            history_messages=int(settings["history_messages"]),
            history_messages_used=0,
        )
        context = AgentRequestContext(
            services=self.services, candidate=candidate, actor_username=actor_username,
            chat_id=action["chat_id"], trace=trace,
            confirmation_grant=secrets.token_urlsafe(32),
        )
        try:
            if action["action_type"] == "TASK_CREATE":
                started, started_at = trace.tool_start(
                    "confirm_task_change", "CONFIRMATION_WRITE", {"action_id": action_id}
                )
                confirmed = self.services.pending_actions.confirm_from_frontend(
                    candidate_id=candidate["candidate_id"],
                    actor_username=actor_username,
                    action_id=action_id,
                )
                result = {
                    **confirmed["action"]["result"],
                    "action_id": action_id,
                    "idempotent_replay": confirmed["idempotent_replay"],
                    "persisted": True,
                }
                trace.tool_end(
                    "confirm_task_change", "CONFIRMATION_WRITE", started, started_at,
                    status="SUCCESS",
                    business_refs={"action_id": action_id, "task_id": result.get("task_id", "")},
                )
            else:
                with bind_agent_context(context):
                    result = confirm_application_change.invoke({"action_id": action_id})
            trace.mark_first_chunk()
            summary = trace.finish(status="SUCCESS", output_chars=0)
        except Exception:
            trace.finish(status="FAILED", output_chars=0)
            raise
        return {"result": result, "trace": summary}
