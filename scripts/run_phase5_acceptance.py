from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from typing import Any

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.runner import AgentOutput
from api.main import create_app


class AcceptanceRunner:
    available = True
    model_name = "phase5-acceptance-runner"

    def __init__(self) -> None:
        self.configurations: list[dict[str, Any]] = []

    def run(
        self,
        *,
        message: str,
        history: list[dict[str, str]],
        runtime_config: dict[str, Any] | None = None,
    ) -> AgentOutput:
        self.configurations.append(dict(runtime_config or {}))
        return AgentOutput("Phase 5 配置分流验收回答。", 10, 6)


def expect(response: Any) -> dict[str, Any]:
    if response.status_code >= 400:
        raise RuntimeError(f"{response.request.method} {response.request.url}: {response.status_code} {response.text}")
    return response.json()


def complete_event(response: Any) -> dict[str, Any]:
    if response.status_code != 200:
        raise RuntimeError(f"Agent stream failed: {response.status_code} {response.text}")
    return [json.loads(line) for line in response.text.splitlines() if line][-1]


def run() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        runner = AcceptanceRunner()
        app = create_app(
            db_path=str(root / "business.db"),
            quality_path=str(root / "quality.db"),
            agentops_path=str(root / "agentops.db"),
            session_secret="phase5-acceptance",
            agent_runner=runner,
        )
        admin = TestClient(app)
        demo = TestClient(app)
        try:
            expect(admin.post("/api/auth/login", json={"username": "admin", "password": "admin"}))
            expect(demo.post("/api/auth/login", json={"username": "demo", "password": "demo"}))
            candidate = expect(demo.get("/api/candidate"))["candidate"]
            checks: list[str] = []

            initial = expect(admin.get("/api/agentops/overview"))
            original_stable = initial["release"]["stable_version_id"]
            if initial["release"]["generation"] != 1 or initial["stable"]["status"] != "RELEASED":
                raise RuntimeError("启动时没有创建首个稳定配置")
            checks.append("由环境配置创建不含密钥的首个不可变 stable baseline")

            settings = dict(initial["stable"]["settings"])
            settings["model_name"] = "phase5-canary-model"
            draft = expect(admin.post("/api/agentops/configurations", json={
                "label": "phase5-canary", "settings": settings,
            }))["configuration"]
            if draft["status"] != "DRAFT":
                raise RuntimeError("新配置不是 DRAFT")
            validated = expect(admin.post(
                f"/api/agentops/configurations/{draft['version_id']}/validate",
                json={"expected_revision": draft["revision"]},
            ))["configuration"]
            if validated["status"] != "VALIDATED":
                raise RuntimeError("配置未进入 VALIDATED")
            checks.append("配置按不可变草稿创建并经 revision CAS 显式校验")

            release_payload = {
                "version_id": draft["version_id"], "channel": "CANARY", "canary_percent": 50,
                "expected_generation": 1, "command_id": "phase5:accept:canary",
            }
            released = expect(admin.post("/api/agentops/releases", json=release_payload))
            if released["release"]["generation"] != 2:
                raise RuntimeError("灰度发布未推进 generation")
            replay = expect(admin.post("/api/agentops/releases", json=release_payload))
            if not replay["idempotent_replay"]:
                raise RuntimeError("发布命令重试未幂等")
            stale = admin.post("/api/agentops/releases", json={
                **release_payload, "command_id": "phase5:accept:stale",
            })
            if stale.status_code != 409:
                raise RuntimeError("旧 generation 发布未被 CAS 拒绝")
            checks.append("发布使用 command 幂等与 generation CAS，旧代次不能覆盖新状态")

            selected: dict[str, str] = {}
            for index in range(500):
                chat_id = f"chat:phase5-cohort-{index}"
                channel = app.state.services.agentops.select_configuration(
                    f"{candidate['candidate_id']}:{chat_id}"
                )["channel"]
                selected.setdefault(channel, chat_id)
                if len(selected) == 2:
                    break
            if set(selected) != {"STABLE", "CANARY"}:
                raise RuntimeError("未观察到 stable/canary 两个确定性 cohort")
            traces = []
            for channel in ("STABLE", "CANARY"):
                complete = complete_event(demo.post("/api/agent/chat/stream", json={
                    "chat_id": selected[channel],
                    "message": f"PRIVATE-PHASE5-{channel}-MARKER",
                }))
                traces.append(complete["trace"])
                if complete["runtime"]["release_channel"] != channel:
                    raise RuntimeError(f"请求没有命中预期 {channel} 通道")
            if {item["release_channel"] for item in traces} != {"STABLE", "CANARY"}:
                raise RuntimeError("Trace 未记录两个发布通道")
            checks.append("真实 Agent 请求按稳定哈希分流，配置版本、通道和 generation 进入 Trace")

            overview = expect(admin.get("/api/agentops/overview?window_minutes=60"))
            metrics = overview["metrics"]
            if metrics["run_count"] != 2 or set(metrics["by_channel"]) != {"STABLE", "CANARY"}:
                raise RuntimeError("运行监控没有聚合 stable/canary")
            if metrics["total_ms_p50"] is None or metrics["total_ms_p95"] is None:
                raise RuntimeError("P50/P95 未计算")
            checks.append("控制台聚合 Run、错误率、P50/P95、Token 与通道/配置计数")

            connection = sqlite3.connect(str(root / "quality.db"))
            try:
                quality_dump = "\n".join(connection.iterdump())
            finally:
                connection.close()
            if "PRIVATE-PHASE5" in quality_dump or "chain_of_thought" in quality_dump:
                raise RuntimeError("Phase 5 Trace 泄漏聊天或隐藏推理")
            checks.append("Trace 管理接口继续遵守 PII allowlist，不保存聊天与隐藏思维链")

            evaluation = expect(admin.post("/api/agentops/evaluations/run", json={
                "baseline_name": "phase5-acceptance", "update_baseline": True,
            }))["evaluation"]
            replayed = expect(admin.post("/api/agentops/evaluations/replay", json={
                "baseline_name": "phase5-acceptance", "update_baseline": False,
            }))["evaluation"]
            if evaluation["passed"] != 8 or replayed["passed"] != 8 or replayed["baseline"]["status"] != "MATCH":
                raise RuntimeError("固定评测或基线回放不一致")
            detail = expect(admin.get(f"/api/agentops/evaluations/{replayed['eval_run_id']}"))["evaluation"]
            if len(detail["results"]) != 8:
                raise RuntimeError("评测详情缺少逐用例结果")
            checks.append("管理 API 跑通 8/8 隔离评测、基线更新、回放 MATCH 与逐用例详情")

            rolled = expect(admin.post("/api/agentops/rollback", json={
                "target_version_id": original_stable,
                "expected_generation": 2,
                "command_id": "phase5:accept:rollback",
                "reason": "acceptance rollback",
            }))
            if rolled["release"]["generation"] != 3 or rolled["release"]["canary_version_id"]:
                raise RuntimeError("回滚没有推进 generation 或清空灰度")
            checks.append("回滚到已发布版本并原子清空 canary，审计保留前后代次")

            if demo.get("/api/agentops/overview").status_code != 403:
                raise RuntimeError("普通用户访问了 AgentOps 控制面")
            if set(app.state.services.agentops.store.table_names()) != {
                "agent_config_versions", "agent_release_state", "agent_release_audit", "agentops_commands",
            }:
                raise RuntimeError("AgentOps 表结构不符合 Phase 5 边界")
            sidebar = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
            if sidebar.count("{ id: '") != 6 or "adminOnly: true" not in sidebar:
                raise RuntimeError("前端没有管理员专属第六页面")
            checks.append("AgentOps API 与第六页面仅管理员可见，业务库仍为 9 张表")

            print("PHASE 5 ACCEPTANCE: PASS")
            for index, item in enumerate(checks, 1):
                print(f"  {index}. PASS - {item}")
            print("  eval=8/8, replay=MATCH, generations=1->2->3, channels=stable+canary, pages=6")
        finally:
            admin.close()
            demo.close()


if __name__ == "__main__":
    run()
