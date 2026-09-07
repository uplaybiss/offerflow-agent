from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from agent.runner import PROMPT_VERSION
from agent.tools import TOOLSET_VERSION
from agentops.store import AgentOpsStore
from core.errors import ConflictError, ValidationError


COMMAND_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{8,100}$")
ALLOWED_SETTING_KEYS = {
    "model_name", "max_retries", "temperature", "history_messages",
    "prompt_version", "toolset_version", "rule_version",
}


def agentops_database_path() -> str:
    configured = os.getenv("OFFERFLOW_AGENTOPS_DB_PATH", "runtime/agentops.db")
    path = Path(configured)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    return str(path.resolve())


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _actor_ref(actor: str) -> str:
    return hashlib.sha256(str(actor).encode("utf-8")).hexdigest()[:16]


class AgentOpsService:
    def __init__(self, store: AgentOpsStore) -> None:
        self.store = store
        self.store.initialize()
        settings = self.default_settings()
        self.store.bootstrap(
            settings=settings,
            settings_sha256=_hash(settings),
            actor_ref=_actor_ref("system-bootstrap"),
        )

    @staticmethod
    def default_settings() -> dict[str, Any]:
        try:
            retries = int(os.getenv("AGENT_MODEL_MAX_RETRIES", "2"))
        except ValueError:
            retries = 2
        try:
            history = int(os.getenv("AGENT_HISTORY_MESSAGES", "12"))
        except ValueError:
            history = 12
        return {
            "model_name": os.getenv("CHAT_MODEL_NAME", "qwen3-max").strip() or "qwen3-max",
            "max_retries": max(0, min(retries, 5)),
            "temperature": 0.0,
            "history_messages": max(1, min(history, 20)),
            "prompt_version": PROMPT_VERSION,
            "toolset_version": TOOLSET_VERSION,
            "rule_version": os.getenv("MATCH_HEURISTIC_VERSION", "heuristic_v1") or "heuristic_v1",
        }

    @staticmethod
    def validate_settings(settings: Any) -> dict[str, Any]:
        errors: list[str] = []
        if not isinstance(settings, dict):
            return {"valid": False, "errors": ["settings 必须是 JSON 对象"]}
        unknown = sorted(set(settings) - ALLOWED_SETTING_KEYS)
        if unknown:
            errors.append(f"存在未允许的配置项：{', '.join(unknown)}")
        model_name = str(settings.get("model_name") or "").strip()
        if not model_name or len(model_name) > 200:
            errors.append("model_name 不能为空且不能超过 200 字符")
        for key, lower, upper in (("max_retries", 0, 5), ("history_messages", 1, 20)):
            try:
                value = int(settings.get(key))
            except (TypeError, ValueError):
                errors.append(f"{key} 必须是整数")
                continue
            if value < lower or value > upper:
                errors.append(f"{key} 必须在 {lower}-{upper} 之间")
        try:
            temperature = float(settings.get("temperature"))
            if temperature < 0 or temperature > 1:
                errors.append("temperature 必须在 0-1 之间")
        except (TypeError, ValueError):
            errors.append("temperature 必须是数字")
        expected_versions = {
            "prompt_version": PROMPT_VERSION,
            "toolset_version": TOOLSET_VERSION,
            "rule_version": os.getenv("MATCH_HEURISTIC_VERSION", "heuristic_v1") or "heuristic_v1",
        }
        for key, expected in expected_versions.items():
            if str(settings.get(key) or "") != expected:
                errors.append(f"{key} 当前只允许 {expected}")
        return {"valid": not errors, "errors": errors}

    def create_configuration(self, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        label = str(payload.get("label") or "").strip()
        if not label or len(label) > 100:
            raise ValidationError("label 不能为空且不能超过 100 字符")
        settings = payload.get("settings")
        validation = self.validate_settings(settings)
        if not isinstance(settings, dict):
            raise ValidationError(validation["errors"][0])
        return self.store.create_configuration(
            label=label,
            settings=dict(settings),
            settings_sha256=_hash(settings),
            actor_ref=_actor_ref(actor),
        )

    def validate_configuration(self, version_id: str, expected_revision: int, actor: str) -> dict[str, Any]:
        version = self.store.get_configuration(version_id)
        validation = self.validate_settings(version["settings"])
        if not validation["valid"]:
            raise ValidationError("；".join(validation["errors"]))
        return self.store.validate_configuration(
            version_id=version_id,
            expected_revision=int(expected_revision),
            validation=validation,
            actor_ref=_actor_ref(actor),
        )

    @staticmethod
    def _command(value: Any) -> str:
        command_id = str(value or "").strip()
        if not COMMAND_PATTERN.fullmatch(command_id):
            raise ValidationError("command_id 需为 8-100 位字母、数字或 ._:-")
        return command_id

    def publish(self, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        version_id = str(payload.get("version_id") or "").strip()
        channel = str(payload.get("channel") or "").upper()
        try:
            expected_generation = int(payload.get("expected_generation"))
        except (TypeError, ValueError):
            raise ValidationError("expected_generation 必须是整数") from None
        state = self.store.release_state()
        if channel == "STABLE":
            stable_id = version_id
            canary_id = ""
            percent = 0.0
            event_type = "STABLE_RELEASED"
        elif channel == "CANARY":
            try:
                percent = float(payload.get("canary_percent"))
            except (TypeError, ValueError):
                raise ValidationError("canary_percent 必须是数字") from None
            if percent <= 0 or percent > 50:
                raise ValidationError("灰度比例必须大于 0 且不超过 50%")
            stable_id = state["stable_version_id"]
            canary_id = version_id
            event_type = "CANARY_RELEASED"
        else:
            raise ValidationError("channel 必须是 STABLE 或 CANARY")
        command_id = self._command(payload.get("command_id"))
        operation = {
            "version_id": version_id,
            "channel": channel,
            "canary_percent": percent,
            "expected_generation": expected_generation,
        }
        return self.store.mutate_release(
            command_id=command_id,
            scope="publish",
            payload_hash=_hash(operation),
            expected_generation=expected_generation,
            stable_version_id=stable_id,
            canary_version_id=canary_id,
            canary_percent=percent,
            version_id=version_id,
            actor_ref=_actor_ref(actor),
            event_type=event_type,
            detail={"channel": channel, "previous_generation": expected_generation},
        )

    def rollback(self, payload: dict[str, Any], actor: str) -> dict[str, Any]:
        target = str(payload.get("target_version_id") or "").strip()
        try:
            expected_generation = int(payload.get("expected_generation"))
        except (TypeError, ValueError):
            raise ValidationError("expected_generation 必须是整数") from None
        command_id = self._command(payload.get("command_id"))
        reason = str(payload.get("reason") or "").strip()[:500]
        operation = {
            "target_version_id": target,
            "expected_generation": expected_generation,
            "reason": reason,
        }
        return self.store.mutate_release(
            command_id=command_id,
            scope="rollback",
            payload_hash=_hash(operation),
            expected_generation=expected_generation,
            stable_version_id=target,
            canary_version_id="",
            canary_percent=0,
            version_id=target,
            actor_ref=_actor_ref(actor),
            event_type="ROLLED_BACK",
            detail={"reason": reason, "previous_generation": expected_generation},
        )

    def select_configuration(self, cohort_key: str) -> dict[str, Any]:
        state = self.store.release_state()
        selected_id = state["stable_version_id"]
        channel = "STABLE"
        reason = "stable-default"
        if state["canary_version_id"] and state["canary_percent"] > 0:
            bucket_key = f"{state['generation']}:{cohort_key or 'anonymous'}"
            bucket = int(hashlib.sha256(bucket_key.encode("utf-8")).hexdigest()[:12], 16) % 10_000
            if bucket < int(round(state["canary_percent"] * 100)):
                selected_id = state["canary_version_id"]
                channel = "CANARY"
                reason = f"canary-bucket-{bucket}"
        if not selected_id:
            raise ConflictError("没有可用的稳定运行配置")
        version = self.store.get_configuration(selected_id)
        return {
            **version,
            "channel": channel,
            "generation": state["generation"],
            "selection_reason": reason,
        }

    def overview(self, quality: Any, window_minutes: int = 60) -> dict[str, Any]:
        state = self.store.release_state()
        return {
            "release": state,
            "stable": self.store.get_configuration(state["stable_version_id"]) if state["stable_version_id"] else None,
            "canary": self.store.get_configuration(state["canary_version_id"]) if state["canary_version_id"] else None,
            "versions": self.store.list_configurations(),
            "metrics": quality.runtime_metrics(window_minutes=window_minutes),
            "recent_traces": quality.list_runs(limit=20),
            "recent_evaluations": quality.list_eval_runs(limit=20),
            "audit": self.store.list_audit(limit=30),
            "deployment_mode": "local-single-process",
            "disclosure": "stable/canary 为确定性哈希分流；本地控制面不等同于分布式配置中心。",
        }
