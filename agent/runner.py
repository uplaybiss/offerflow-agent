from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Protocol

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

from agent.tools import CAREER_TOOL_CATALOG, CAREER_TOOL_NAMES
from core.errors import ExternalServiceError


PROMPT_VERSION = "career-agent-prompt-v3"


@dataclass
class AgentOutput:
    answer: str
    input_tokens: int = 0
    output_tokens: int = 0


class AgentRunner(Protocol):
    available: bool
    model_name: str

    def run(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        runtime_config: dict[str, Any] | None = None,
    ) -> AgentOutput: ...


class LangChainCareerAgentRunner:
    def __init__(self) -> None:
        key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        self._api_key = key
        self.available = bool(key and not key.lower().startswith("your_"))
        self.model_name = os.getenv("CHAT_MODEL_NAME", "qwen3-max").strip() or "qwen3-max"
        self.base_url = os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).strip().rstrip("/")
        try:
            self.max_retries = max(0, min(int(os.getenv("AGENT_MODEL_MAX_RETRIES", "2")), 5))
        except ValueError:
            self.max_retries = 2
        self._prompt = (
            Path(__file__).resolve().parents[1] / "prompts" / "career_agent_v1.txt"
        ).read_text(encoding="utf-8")
        self._graphs: dict[str, Any] = {}

    def _graph_for(self, settings: dict[str, Any]) -> Any:
        enabled_tools = self._enabled_tool_names(settings)
        skill_name = str(settings.get("_active_skill") or "")
        skill_prompt = str(settings.get("_skill_prompt") or "").strip()
        effective = {
            "model_name": str(settings.get("model_name") or self.model_name),
            "max_retries": max(0, min(int(settings.get("max_retries", self.max_retries)), 5)),
            "temperature": max(0.0, min(float(settings.get("temperature", 0)), 1.0)),
            "enabled_tools": enabled_tools,
            "active_skill": skill_name,
            "skill_prompt_sha256": hashlib.sha256(skill_prompt.encode("utf-8")).hexdigest(),
        }
        cache_key = hashlib.sha256(
            json.dumps(effective, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        graph = self._graphs.get(cache_key)
        if graph is None:
            model = ChatOpenAI(
                model=effective["model_name"],
                api_key=self._api_key,
                base_url=self.base_url,
                streaming=False,
                temperature=effective["temperature"],
                max_retries=effective["max_retries"],
                extra_body={"enable_thinking": False},
            )
            system_prompt = self._prompt
            if skill_prompt:
                system_prompt += f"\n\n当前请求激活静态 Skill /{skill_name}：\n{skill_prompt}"
            graph = create_agent(
                model=model,
                tools=[CAREER_TOOL_CATALOG[name] for name in enabled_tools],
                system_prompt=system_prompt,
            )
            self._graphs[cache_key] = graph
        return graph

    @staticmethod
    def _enabled_tool_names(settings: dict[str, Any]) -> list[str]:
        configured = settings.get("enabled_tools", list(CAREER_TOOL_NAMES))
        if not isinstance(configured, list):
            raise ValueError("enabled_tools must be a list")
        names = list(dict.fromkeys(str(item) for item in configured))
        if not names or any(name not in CAREER_TOOL_CATALOG for name in names):
            raise ValueError("enabled_tools contains unknown or empty tool selection")
        return names

    def tools_for(self, settings: dict[str, Any]) -> list[str]:
        """Expose the effective schema names for deterministic contract tests."""
        return self._enabled_tool_names(settings)

    @staticmethod
    def _content(message: Any) -> str:
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text", "")) if isinstance(item, dict) else str(item)
                for item in content
            )
        return str(content or "")

    def run(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        runtime_config: dict[str, Any] | None = None,
    ) -> AgentOutput:
        if not self.available:
            raise ExternalServiceError("Career Agent 未配置可用的 DASHSCOPE_API_KEY；其他手工工作台功能不受影响")
        settings = runtime_config or {}
        try:
            history_messages = max(1, min(int(settings.get("history_messages", 12)), 20))
            graph = self._graph_for(settings)
        except (TypeError, ValueError) as exc:
            raise ExternalServiceError("Career Agent 运行配置无效") from exc
        messages = [
            {"role": item["role"], "content": item["content"]}
            for item in history[-history_messages:]
            if item.get("role") in {"user", "assistant"} and item.get("content")
        ]
        messages.append({"role": "user", "content": message})
        result = graph.invoke({"messages": messages})
        output_messages = result.get("messages", [])
        answer = self._content(output_messages[-1]) if output_messages else ""
        input_tokens = 0
        output_tokens = 0
        for item in output_messages:
            usage = getattr(item, "usage_metadata", None) or {}
            input_tokens += int(usage.get("input_tokens", 0) or 0)
            output_tokens += int(usage.get("output_tokens", 0) or 0)
        return AgentOutput(answer=answer or "没有生成可展示的回答。", input_tokens=input_tokens, output_tokens=output_tokens)
