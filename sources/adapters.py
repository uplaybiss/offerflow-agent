from __future__ import annotations

from typing import Any, Iterable, Protocol


SOURCE_ADAPTER_CONTRACT_VERSION = "source_adapter_v1"


class SourceAdapter(Protocol):
    key: str
    display_name: str

    def fetch_job(self, job: dict[str, Any]) -> dict[str, Any]: ...


class SourceAdapterRegistry:
    def __init__(self, adapters: Iterable[SourceAdapter] = ()) -> None:
        self._adapters: dict[str, SourceAdapter] = {}
        for adapter in adapters:
            key = str(adapter.key or "").strip()
            if not key or key in self._adapters:
                raise ValueError("source adapter key must be unique and non-empty")
            self._adapters[key] = adapter

    def get(self, key: str) -> SourceAdapter | None:
        return self._adapters.get(str(key or "").strip())

    def capabilities(self) -> dict[str, Any]:
        return {
            "contract_version": SOURCE_ADAPTER_CONTRACT_VERSION,
            "persistence": "preview_then_user_patch",
            "adapters": [
                {"key": adapter.key, "display_name": adapter.display_name}
                for adapter in self._adapters.values()
            ],
        }
