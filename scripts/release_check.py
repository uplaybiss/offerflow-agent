from __future__ import annotations

from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.tools import CAREER_TOOLS
from agentops.service import AgentOpsService
from agentops.store import AgentOpsStore
from core.database import Database
from quality.contract_eval import CONTRACT_CASES, CONTRACT_SUITE_VERSION
from quality.eval import FIXED_CASES
from quality.store import QualityStore


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BUSINESS_TABLES = {
    "users", "candidate_profiles", "jobs", "applications", "application_events",
    "interview_rounds", "job_search_tasks", "agent_memories", "pending_actions",
    "resume_versions", "chat_threads", "chat_messages",
}
EXPECTED_QUALITY_TABLES = {
    "agent_runs", "trace_events", "eval_runs", "eval_case_results", "eval_baselines",
}
EXPECTED_AGENTOPS_TABLES = {
    "agent_config_versions", "agent_release_state", "agent_release_audit", "agentops_commands",
}
DEFERRED_MODELS = {"candidate_skills"}


def main() -> None:
    with tempfile.TemporaryDirectory() as folder:
        database = Database(str(Path(folder) / "release.db")); database.initialize()
        business_tables = set(database.table_names())
        quality = QualityStore(str(Path(folder) / "quality.db")); quality.initialize()
        with quality.connection() as connection:
            quality_tables = {
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        agentops = AgentOpsService(AgentOpsStore(str(Path(folder) / "agentops.db")))
        agentops_tables = set(agentops.store.table_names())
    if business_tables != EXPECTED_BUSINESS_TABLES:
        raise SystemExit(f"unexpected business tables: {sorted(business_tables)}")
    if quality_tables != EXPECTED_QUALITY_TABLES:
        raise SystemExit(f"unexpected quality tables: {sorted(quality_tables)}")
    if agentops_tables != EXPECTED_AGENTOPS_TABLES:
        raise SystemExit(f"unexpected AgentOps tables: {sorted(agentops_tables)}")

    active_roots = ("core", "career", "api", "parsing", "matching", "agent", "quality", "agentops")
    source = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore").lower()
        for name in active_roots
        for path in (ROOT / name).rglob("*.py")
    )
    residues = sorted(
        name for name in DEFERRED_MODELS
        if any(sql in source for sql in (f"create table {name}", f"insert into {name}", f"from {name}", f"update {name}"))
    )
    if residues:
        raise SystemExit(f"deferred table residue: {residues}")
    if (ROOT / "rag").exists():
        raise SystemExit("deferred RAG directory appeared in v5.2")
    removed_source_modules = (
        ROOT / "sources" / "adapters.py",
        ROOT / "career" / "services" / "sources.py",
        ROOT / "api" / "routers" / "sources.py",
    )
    if any(path.exists() for path in removed_source_modules):
        raise SystemExit("online job-source adapter modules must stay removed")

    required_files = (
        ROOT / "agent" / "context.py",
        ROOT / "agent" / "tools.py",
        ROOT / "agent" / "runner.py",
        ROOT / "agent" / "service.py",
        ROOT / "prompts" / "career_agent_v1.txt",
        ROOT / "quality" / "trace.py",
        ROOT / "quality" / "eval.py",
        ROOT / "career" / "repositories" / "memory.py",
        ROOT / "career" / "repositories" / "pending_actions.py",
        ROOT / "career" / "repositories" / "resumes.py",
        ROOT / "career" / "repositories" / "chats.py",
        ROOT / "career" / "services" / "resumes.py",
        ROOT / "career" / "services" / "chats.py",
        ROOT / "api" / "routers" / "resumes.py",
        ROOT / "api" / "routers" / "chats.py",
        ROOT / "frontend" / "src" / "views" / "CareerAgentView.vue",
        ROOT / "frontend" / "src" / "views" / "ResumeCenterView.vue",
        ROOT / "frontend" / "src" / "uiLabels.ts",
        ROOT / "agentops" / "store.py",
        ROOT / "agentops" / "service.py",
        ROOT / "quality" / "management.py",
        ROOT / "quality" / "scenarios.py",
        ROOT / "quality" / "contract_eval.py",
        ROOT / "quality" / "contract_scenarios.py",
        ROOT / "api" / "schemas.py",
        ROOT / "api" / "routers" / "agentops.py",
        ROOT / "frontend" / "src" / "views" / "AgentOpsView.vue",
        ROOT / "scripts" / "run_phase5_acceptance.py",
        ROOT / "scripts" / "run_phase5_live_agent_smoke.py",
        ROOT / "scripts" / "run_final_hardening_acceptance.py",
        ROOT / "scripts" / "run_v52_real_usage_acceptance.py",
        ROOT / "OfferFlow Final Hardening 报告.md",
    )
    missing = [str(path.relative_to(ROOT)) for path in required_files if not path.exists()]
    if missing:
        raise SystemExit(f"required Phase 5 modules missing: {missing}")

    expected_tools = {
        "get_candidate_360", "search_jobs", "get_job_detail", "analyze_job_match", "compare_jobs",
        "analyze_skill_gaps", "query_applications", "list_upcoming_tasks",
        "analyze_resume_for_job", "propose_application_change", "propose_task_change",
        "confirm_application_change",
    }
    if len(CAREER_TOOLS) != 12 or {item.name for item in CAREER_TOOLS} != expected_tools:
        raise SystemExit("Career Agent must expose the confirmed v5.2 12-tool catalog")
    if any("candidate_id" in item.args for item in CAREER_TOOLS):
        raise SystemExit("Career Agent tool schemas must not accept candidate_id")
    if len(FIXED_CASES) != 8:
        raise SystemExit("fixed Phase 4 evaluation set must contain 8 cases")
    if len(CONTRACT_CASES) != 8 or CONTRACT_SUITE_VERSION != "career-agent-contract-v1":
        raise SystemExit("Agent Contract / Safety suite must contain 8 scripted cases")

    pending_source = (ROOT / "career" / "repositories" / "pending_actions.py").read_text(encoding="utf-8")
    if not all(term in pending_source for term in ("transaction()", "AGENT_STATUS_CHANGED", "INTERVIEW_PROGRESSED", "INTERVIEW_PROGRESSION", "TASK_CREATE", "confirmation_grant_hash", "expected_version")):
        raise SystemExit("atomic confirmation / CAS contract missing")
    trace_source = (ROOT / "quality" / "trace.py").read_text(encoding="utf-8")
    if not all(term in trace_source for term in ("ALLOWED_BUSINESS_REF_KEYS", "ALLOWED_METRIC_KEYS", "opaque_ref")):
        raise SystemExit("PII allowlist trace contract missing")
    agentops_source = (ROOT / "agentops" / "service.py").read_text(encoding="utf-8")
    if not all(term in agentops_source for term in ("select_configuration", "expected_generation", "CANARY", "rollback", "enabled_tools", "TOOL_RISKS")):
        raise SystemExit("Phase 5 stable/canary generation control missing")
    runner_source = (ROOT / "agent" / "runner.py").read_text(encoding="utf-8")
    if not all(term in runner_source for term in ("enabled_tools", "CAREER_TOOL_CATALOG", "history[-history_messages:]")):
        raise SystemExit("runtime history window or Tool whitelist is not enforced by Agent Runner")

    dist = ROOT / "frontend" / "dist" / "index.html"
    if not dist.exists():
        raise SystemExit("frontend production build missing")
    sidebar = (ROOT / "frontend" / "src" / "components" / "AppSidebar.vue").read_text(encoding="utf-8")
    expected_user_pages = ("今日工作台", "岗位中心", "简历中心", "投递进度", "个人中心", "求职 Agent")
    if sidebar.count("{ id: '") != 7 or not all(label in sidebar for label in expected_user_pages) or "AgentOps" not in sidebar:
        raise SystemExit("v5.2 must expose six user pages plus admin-only AgentOps")
    agent_view = (ROOT / "frontend" / "src" / "views" / "CareerAgentView.vue").read_text(encoding="utf-8")
    if not all(term in agent_view for term in ("/api/agent/chat/stream", "/api/chat-threads", "/confirm", "待你确认", "最近对话")):
        raise SystemExit("Career Agent page is not fully wired")
    agentops_view = (ROOT / "frontend" / "src" / "views" / "AgentOpsView.vue").read_text(encoding="utf-8")
    if not all(term in agentops_view for term in ("generation CAS", "发布灰度", "回滚到此", "Agent Contract / Safety Eval", "Tool Whitelist", "Trace 时间线")):
        raise SystemExit("AgentOps page is not fully wired")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required_disclosures = (
        "# 第一次使用 OfferFlow", "AI 求职投递与简历优化工作台",
        "deterministic matching", "confirmation write", "实时联网搜索岗位",
        "自动投递", "多 Agent", "RAG", "分布式服务", "ResumeVersion",
        "聊天记录", "AgentMemory", "Trace",
    )
    if not all(term in readme for term in required_disclosures):
        raise SystemExit("README release-candidate scope disclosure is incomplete")

    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    if not all(name in requirements for name in ("langchain==", "langchain-openai==")):
        raise SystemExit("pinned Career Agent runtime dependencies missing")
    forbidden_automation = [name for name in ("selenium", "playwright", "scrapy") if name in requirements]
    if forbidden_automation:
        raise SystemExit(f"forbidden crawler/browser dependencies: {forbidden_automation}")

    print("OFFERFLOW V5.2 RELEASE CHECK: PASS")
    print("  12 business tables; 5 quality tables; 4 AgentOps tables; 12 tools; immutable whitelist; atomic confirmation; 8 business regressions + 8 scripted contract cases; 6 user pages + admin AgentOps")


if __name__ == "__main__":
    main()
