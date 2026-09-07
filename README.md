# OfferFlow Agent（Phase 5）

独立的秋招求职 Agent 工作台。当前版本在候选人、岗位、投递、面试、待办、结构化解析、确定性 Matching 与 Career Agent 之上，增加可审计的 AgentOps 配置发布、stable/canary 分流、运行监控、Trace 查看和固定评测回放。

## 当前能力

- 手工维护候选人档案、当前简历、岗位、投递状态机、面试轮次和求职待办
- TXT/PDF 简历文本提取，以及可选 Qwen 简历/JD 结构化预览
- 基于 `heuristic_v1` 展示硬条件、required/preferred skill coverage 和具体缺口；分数不是录用概率
- 根据岗位截止、测评和面试时间生成可追溯建议，用户确认后才保存为待办
- LangChain Tool Calling Career Agent 通过十个受控工具查询真实业务数据
- Agent 工具不接收 `candidate_id`；当前用户、候选人及对象上下文由服务端注入
- 投递写入遵循“提议 → 确认卡 → 结构化第二次请求 → 原子迁移”，模型不能自行确认
- PendingAction 绑定 action、actor、请求哈希、过期时间和 Application `version` CAS
- AgentMemory 只保存活对象引用和受控意图标签，不持久化完整聊天、简历或 JD
- NDJSON 对话响应；Trace 只保存 allowlist 元数据，不保存 CoT、聊天全文、完整 JD 或简历 PII
- 不可变 Agent 配置版本，支持 `DRAFT → VALIDATED → RELEASED`
- stable/canary 确定性分流、发布命令幂等、`generation` CAS 与一键回滚
- 按时间窗口统计 Run 数、错误率、P50/P95、Token、发布通道及配置版本分布
- 固定 8 条隔离评测、基线更新与确定性回放比较
- 六个主页面；AgentOps 页面仅管理员可见，相关 API 也强制管理员鉴权
- SQLite WAL 持久化；业务时间存 UTC，展示时区默认 `Asia/Shanghai` 且可配置

## 十个 Agent 工具

读取工具：

1. `get_candidate_360`
2. `search_jobs`
3. `get_job_detail`
4. `analyze_job_match`
5. `compare_jobs`
6. `analyze_skill_gaps`
7. `query_applications`
8. `list_upcoming_tasks`

写入控制工具：

9. `propose_application_change`：只创建确认卡，不改变 Application
10. `confirm_application_change`：只接受确认卡第二次请求生成的服务端授权

## 本地运行（PowerShell 7）

```powershell
cd D:\offerflow-agent
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
corepack pnpm --dir frontend install
corepack pnpm --dir frontend build
Copy-Item .env.example .env
# 在 .env 填写有效的 DASHSCOPE_API_KEY，并按百炼控制台设置模型和 Base URL
.\.venv\Scripts\python.exe app.py
```

浏览器打开 `http://127.0.0.1:8000`。首次启动会为本地开发创建 `demo/demo` 与 `admin/admin`。AgentOps 使用 `admin/admin` 登录；非本地使用前必须更换默认密码和 `SESSION_SECRET`。

没有模型 Key 时，五个非 AgentOps 业务页面、确定性 Matching 以及 AgentOps 离线评测仍可使用；真实 Agent 对话和 LLM 结构化解析需要有效的 DashScope 兼容接口配置。

## 关键配置

```text
OFFERFLOW_DB_PATH=runtime/offerflow.db
OFFERFLOW_QUALITY_DB_PATH=runtime/quality.db
OFFERFLOW_AGENTOPS_DB_PATH=runtime/agentops.db
APP_TIMEZONE=Asia/Shanghai
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CHAT_MODEL_NAME=qwen3-max
AGENT_MODEL_MAX_RETRIES=2
AGENT_HISTORY_MESSAGES=12
PENDING_ACTION_TTL_SECONDS=900
```

三个 SQLite 文件职责分离：

- `offerflow.db`：9 张业务表。
- `quality.db`：Run、Trace、评测结果与基线。
- `agentops.db`：不可变配置版本、当前发布状态、发布审计和幂等命令。

API Key、Base URL、聊天全文、完整简历和完整 JD 不写入 `agentops.db` 或 `quality.db`。AgentOps 配置只管理允许发布的运行参数。

## AgentOps 使用

1. 使用管理员账号进入“运行控制”。
2. 创建不可变草稿；草稿只能验证，不能原地修改。
3. 验证成功后发布到 stable，或按 `1%–50%` 发布到 canary。
4. 发布请求必须携带页面读取到的当前 `generation`；过期 generation 会被拒绝，重复 `command_id` 不会重复发布。
5. canary 按候选人与会话组成的 cohort 做稳定哈希，同一 generation 下不会随机跳组。
6. 在同一页面查看运行指标、Trace、固定评测及基线回放；异常时回滚到已验证版本。

回滚恢复的是运行配置，不回滚业务数据库。P50/P95 在样本很少时仅反映当前窗口内样本，不应当作长期性能结论。项目没有维护带生效时间的模型价格目录，因此不输出推测成本。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_phase1_acceptance.py
.\.venv\Scripts\python.exe scripts\run_phase2_acceptance.py
.\.venv\Scripts\python.exe scripts\run_phase3_acceptance.py
.\.venv\Scripts\python.exe scripts\run_phase4_acceptance.py
.\.venv\Scripts\python.exe scripts\run_phase5_acceptance.py
corepack pnpm --dir frontend exec vue-tsc --noEmit
corepack pnpm --dir frontend build
.\.venv\Scripts\python.exe scripts\release_check.py
```

可选真实模型冒烟：

```powershell
.\.venv\Scripts\python.exe scripts\run_phase5_live_agent_smoke.py
```

真实模型冒烟只使用临时合成数据，不读取或修改正式业务库。

## 明确边界

当前仍不实现 RAG、ResumeVersion、CandidateSkill 独立表、官网大规模抓取、自动登录、自动投递、邮件发送或 HR 联系。固定评测回放是隔离夹具上的确定性回归，不是重放任意历史聊天；为保护隐私，系统没有保存完成任意聊天重放所需的原始消息。
