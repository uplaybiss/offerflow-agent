from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

import httpx

from core.errors import ExternalServiceError, ValidationError


class LlmClient(Protocol):
    @property
    def available(self) -> bool: ...

    @property
    def provider(self) -> str: ...

    @property
    def model(self) -> str: ...

    def complete_json(self, *, task: str, instructions: str, input_text: str) -> dict[str, Any]: ...

    def complete_text(self, *, task: str, instructions: str, facts: dict[str, Any]) -> str: ...


class DashScopeLlmClient:
    def __init__(self) -> None:
        self._api_key = os.getenv("DASHSCOPE_API_KEY", "").strip()
        self._base_url = os.getenv(
            "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        self._model = os.getenv("CHAT_MODEL_NAME", "qwen3-max").strip() or "qwen3-max"
        try:
            self._timeout = max(10.0, min(float(os.getenv("LLM_TIMEOUT_SECONDS", "60")), 180.0))
        except ValueError:
            self._timeout = 60.0

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def provider(self) -> str:
        return "dashscope"

    @property
    def model(self) -> str:
        return self._model

    def _request(self, messages: list[dict[str, str]], *, json_mode: bool) -> str:
        if not self.available:
            raise ExternalServiceError("未配置 DASHSCOPE_API_KEY；仍可手工填写并保存")
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 3000,
            "enable_thinking": False,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                json=body,
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"] or "").strip()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                raise ExternalServiceError("模型鉴权失败，请检查 DASHSCOPE_API_KEY") from None
            raise ExternalServiceError(f"模型服务返回异常状态 {status}") from None
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            raise ExternalServiceError("模型服务暂时不可用或响应格式异常") from None

    def complete_json(self, *, task: str, instructions: str, input_text: str) -> dict[str, Any]:
        content = self._request(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 OfferFlow 的结构化信息提取器。只能提取输入明确出现或可直接确定的事实；"
                        "不猜测，不补全未知值。严格输出一个 JSON 对象，不要 Markdown。\n" + instructions
                    ),
                },
                {"role": "user", "content": f"任务：{task}\n\n原文：\n{input_text}"},
            ],
            json_mode=True,
        )
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError:
            raise ExternalServiceError("模型没有返回合法 JSON，请重试或手工填写") from None
        if not isinstance(result, dict):
            raise ExternalServiceError("模型返回的预览不是 JSON 对象")
        return result

    def complete_text(self, *, task: str, instructions: str, facts: dict[str, Any]) -> str:
        content = self._request(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 OfferFlow 的求职匹配解释器。只能解释给定的确定性事实，不能修改等级、"
                        "硬条件、命中或缺口，不能把启发式等级描述为录用概率。" + instructions
                    ),
                },
                {"role": "user", "content": f"任务：{task}\n\n确定性事实：\n{json.dumps(facts, ensure_ascii=False, sort_keys=True)}"},
            ],
            json_mode=False,
        )
        if not content:
            raise ExternalServiceError("模型没有返回解释")
        return content[:10_000]


def require_text(value: Any, field: str, *, limit: int = 500_000) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValidationError(f"{field} 不能为空")
    if len(text) > limit:
        raise ValidationError(f"{field} 过长")
    return text
