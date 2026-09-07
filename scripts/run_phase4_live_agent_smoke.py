from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from api.main import create_app


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        app = create_app(
            db_path=str(root / "live-agent.db"),
            quality_path=str(root / "live-agent-quality.db"),
            session_secret="phase4-live-smoke",
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            login = client.post("/api/auth/login", json={"username": "demo", "password": "demo"})
            if login.status_code != 200:
                raise SystemExit("PHASE 4 LIVE AGENT SMOKE: FAIL (login)")
            capabilities = client.get("/api/agent/capabilities").json()
            if not capabilities["available"]:
                raise SystemExit("PHASE 4 LIVE AGENT SMOKE: SKIP (DASHSCOPE_API_KEY not configured)")
            job = client.post("/api/jobs", json={
                "company_name": "Live Smoke Synthetic",
                "title": "AI 应用工程师",
                "location": "上海",
                "deadline": "2030-12-31",
                "required_skills": ["Python", "FastAPI"],
                "preferred_skills": ["Vue 3"],
                "is_favorite": True,
            })
            if job.status_code != 201:
                raise SystemExit("PHASE 4 LIVE AGENT SMOKE: FAIL (fixture)")
            response = client.post("/api/agent/chat/stream", json={
                "chat_id": "chat:phase4-live-smoke",
                "message": "请查询我当前收藏了多少个岗位，只回答数量和公司名。",
            })
            if response.status_code != 200:
                detail = response.json().get("detail", {}) if response.headers.get("content-type", "").startswith("application/json") else {}
                message = detail.get("message", "request failed") if isinstance(detail, dict) else "request failed"
                raise SystemExit(f"PHASE 4 LIVE AGENT SMOKE: FAIL ({response.status_code}: {message})")
            events = [json.loads(line) for line in response.text.splitlines() if line]
            complete = events[-1]
            used_tools = [
                item["tool_name"] for item in complete["trace"]["events"]
                if item["event_type"] == "TOOL_END" and item["status"] == "SUCCESS"
            ]
            if "search_jobs" not in used_tools:
                raise SystemExit(f"PHASE 4 LIVE AGENT SMOKE: FAIL (unexpected tools: {used_tools})")
            print("PHASE 4 LIVE AGENT SMOKE: PASS")
            print(f"  model={capabilities['model']}, tools={used_tools}, trace={complete['trace']['trace_id']}")


if __name__ == "__main__":
    main()
