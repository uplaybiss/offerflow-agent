# OfferFlow Agent《Phase 1 实现报告》

实现日期：2026-09-06
项目目录：`D:\offerflow-agent`
阶段结论：**Phase 1 已完成并通过验收；已停止，未进入 Phase 2。**

## 1. 本阶段交付结论

OfferFlow 已从原“智维通”代码库之外新建为独立 Git 仓库。本阶段交付的是可以立即手工使用的秋招求职 MVP：用户可登录，维护当前候选人档案与简历，手工录入或粘贴岗位，收藏岗位，建立投递，按合法状态推进，查看事件时间线，维护面试轮次与待办，并在工作台查看汇总。

Phase 1 使用 FastAPI + SQLite WAL + Vue 3 + TypeScript。业务生成时间和用户输入的面试/待办时间统一规范化为 UTC 后持久化；前端根据可配置 `APP_TIMEZONE` 展示，默认 `Asia/Shanghai`。

## 2. Phase 0.1 文档残留修正

已修正 `F:\Codex\2026-09-04\q\outputs\智维通 → OfferFlow 迁移分析.md`：

1. 删除 Phase 1 中“JD/简历解析产生 PENDING”的旧设计；LLM 解析确认测试归入 Phase 2，Phase 1 不使用 PendingAction。
2. Phase 1 前端验收固定为 4 个主页面；Phase 4 接入 Career Agent 后才增加到 5 个。
3. 业务时间继续以 UTC 存储；展示时区改为 `APP_TIMEZONE` 可配置，默认 `Asia/Shanghai`，不写死 `Asia/Hong_Kong`。

## 3. 代码与文件清单

### 3.1 入口、环境与交付

- `app.py`：本地启动入口。
- `.env.example`：数据库、时区、Cookie、跨域、监听地址配置示例。
- `requirements.txt`：Phase 1 Python 依赖，包含 Windows IANA 时区数据 `tzdata`。
- `README.md`：启动、开发、测试和边界说明。
- `Dockerfile`、`docker-compose.yml`、`.dockerignore`：容器化运行入口。
- `.github/workflows/ci.yml`：后端测试、前端构建和发布检查。
- `.gitignore`：排除密钥、虚拟环境、依赖、构建产物和运行数据库。

### 3.2 核心基础设施

- `core/database.py`：SQLite 连接、WAL、事务、七表 DDL、JSON 编解码。
- `core/security.py`：PBKDF2 密码存储、登录验证、本地初始账号和用户管理。
- `core/time.py`：UTC 时间、可配置展示时区、输入时间 UTC 规范化。
- `core/errors.py`、`core/ids.py`：领域异常和业务 ID。
- `core/container.py`：Repository/Service 依赖组装。

### 3.3 领域层

- `career/models.py`：Job、Application、Interview、Task 枚举与投递迁移图。
- `career/state_machine.py`：投递初始状态和迁移校验。
- `career/repositories/candidate.py`
- `career/repositories/jobs.py`
- `career/repositories/applications.py`：同时包含 Application/Event 和 Interview Repository。
- `career/repositories/tasks.py`
- `career/services/candidate.py`
- `career/services/jobs.py`
- `career/services/applications.py`：同时包含 Application 和 Interview Service。
- `career/services/tasks.py`：同时包含 Task 和 Workbench Service。

### 3.4 API

- `api/main.py`：应用工厂、中间件、统一领域错误、API 和静态前端挂载。
- `api/dependencies.py`：当前用户、管理员和候选人上下文。
- `api/routers/health.py`
- `api/routers/auth.py`
- `api/routers/candidate.py`
- `api/routers/jobs.py`
- `api/routers/applications.py`
- `api/routers/tasks.py`

### 3.5 前端

- `frontend/src/App.vue`：登录态与四页面壳层。
- `frontend/src/components/AppSidebar.vue`：固定 4 个主页面入口。
- `frontend/src/views/LoginView.vue`
- `frontend/src/views/WorkbenchView.vue`：今日数据汇总、近期面试、待办新增/完成。
- `frontend/src/views/JobCenterView.vue`：岗位录入、粘贴 JD、来源、收藏、筛选、详情和归档。
- `frontend/src/views/ApplicationTrackerView.vue`：投递看板、合法迁移、事件时间线和面试轮次。
- `frontend/src/views/Candidate360View.vue`：基本信息、结构化技能、当前简历和人工解析结构。
- `frontend/src/api.ts`：真实 HTTP 请求、`command_id` 生成和按配置时区展示。
- `frontend/src/styles.css`：完整桌面端 UI 样式。
- `frontend/pnpm-lock.yaml`：前端依赖锁文件。

### 3.6 验证

- `tests/test_phase1.py`：数据库、鉴权、隔离、Candidate、Job、Application、Event、幂等、CAS、Interview、Task、Workbench、时区及四页面契约。
- `scripts/run_phase1_acceptance.py`：Phase 1 端到端验收脚本。
- `scripts/release_check.py`：七表、四页面、延期数据表缺席和前端产物检查。

## 4. 七张数据库表

数据库启用 `journal_mode=WAL`、`foreign_keys=ON` 和写事务 `BEGIN IMMEDIATE`。当前业务表严格为七张：

| 表 | 作用 | 主要约束与 Phase 1 设计 |
|---|---|---|
| `users` | 本地账号 | username 主键；PBKDF2-HMAC-SHA256；admin/user；active |
| `candidate_profiles` | 当前候选人档案 | owner_username 唯一；技能为 JSON；只保存当前简历与解析 JSON；version CAS |
| `jobs` | 岗位池 | 候选人隔离；状态归 Job；内容 SHA-256 去重；预留 source、外部岗位 ID、企业 Career URL；version CAS |
| `applications` | 投递实例 | candidate+job 唯一；最小状态集；下一步、备注和关键状态时间；version CAS |
| `application_events` | 投递事件时间线 | application 内 sequence 唯一；application+command_id 唯一；保存请求哈希和 resulting_version |
| `interview_rounds` | 测评/面试轮次 | application 内 round_no 唯一；计划、已安排、完成、取消；version CAS |
| `job_search_tasks` | 求职待办 | 可关联 Job/Application/Interview；类型、优先级、截止时间、状态；version CAS |

数据库中没有 `resume_versions`、`candidate_skills`、`agent_memories`、`pending_actions`。

## 5. 状态机、Event、幂等和并发控制

Application 状态：

```text
PLANNED ──> APPLIED ──> ASSESSMENT ──> INTERVIEW ──> OFFER
   │           │             │              │
   └───────────┴─────────────┴──────────────┴──> WITHDRAWN
               └─────────────┴───────────────> REJECTED
```

具体规则：

- `PLANNED` 只能进入 `APPLIED` 或 `WITHDRAWN`。
- `APPLIED` 可进入 `ASSESSMENT`、`INTERVIEW`、`OFFER`、`REJECTED`、`WITHDRAWN`，支持企业流程跳过测评/面试。
- `ASSESSMENT` 可进入 `INTERVIEW`、`OFFER`、`REJECTED`、`WITHDRAWN`。
- `INTERVIEW` 可进入 `OFFER`、`REJECTED`、`WITHDRAWN`。
- `OFFER` 仅可进入 `WITHDRAWN`；`REJECTED`、`WITHDRAWN` 为终态。
- 岗位过期是 `jobs.status/effective_status`，不进入 Application 状态。
- 每次创建或状态迁移与 Event 在同一数据库事务提交；失败时整体回滚。
- 调用方提供 `command_id`；服务端保存规范请求的 SHA-256。同一命令、同一请求返回原结果，不重复写事件；同一命令、不同请求返回 409。
- Application、Candidate、Job、Interview、Task 更新均使用 `WHERE version = expected_version` CAS；旧版本返回 409。

## 6. API 清单

共 23 个 Phase 1 操作：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/health` | 健康、UTC 时间和展示时区 |
| POST | `/api/auth/login` | 登录 |
| POST | `/api/auth/logout` | 退出 |
| GET | `/api/auth/me` | 当前用户 |
| GET/POST | `/api/auth/users` | 管理员查看/创建账号 |
| GET/PUT | `/api/candidate` | 读取/保存当前候选人档案 |
| GET/POST | `/api/jobs` | 筛选/新增岗位 |
| GET/PATCH | `/api/jobs/{job_id}` | 岗位详情/更新/收藏/归档 |
| GET/POST | `/api/applications` | 投递列表/建立投递 |
| GET | `/api/applications/{application_id}` | 投递详情和 Event 时间线 |
| POST | `/api/applications/{application_id}/transitions` | 状态迁移 |
| GET | `/api/interviews` | 面试轮次列表 |
| POST | `/api/applications/{application_id}/interviews` | 新增面试轮次 |
| PATCH | `/api/interviews/{round_id}` | 更新面试轮次 |
| GET/POST | `/api/tasks` | 待办列表/新增待办 |
| PATCH | `/api/tasks/{task_id}` | 更新待办 |
| GET | `/api/workbench` | 工作台聚合 |

所有 Candidate、Job、Application、Interview、Task API 都从登录 Session 解析当前用户，并以其 `candidate_id` 作为服务端数据边界；不信任前端传入 candidate_id。

## 7. 自动化测试与前端构建结果

最终执行命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
corepack pnpm --dir frontend build
.\.venv\Scripts\python.exe scripts\run_phase1_acceptance.py
.\.venv\Scripts\python.exe scripts\release_check.py
```

最终结果：

- 后端/契约测试：**9 passed**。
- 覆盖：七表/WAL/外键、可配置时区与 UTC、认证、Candidate CAS、岗位去重与来源、投递状态机、Event、幂等、串行和并发 CAS、面试、待办、工作台、用户隔离、四页面契约。
- TypeScript 类型检查：**通过**。
- Vite 生产构建：**通过**，29 modules transformed。
- 生产产物：`index.html` 0.46 kB；CSS 9.59 kB；JS 90.91 kB（构建哈希会随源码变化）。
- 发布边界检查：**PASS**，七表、四页面、无延期表、生产 bundle 存在。

测试存在两条来自当前 Starlette TestClient 依赖栈的弃用提示（`httpx`/AnyIO 兼容迁移），不影响运行和断言；后续升级依赖时应改用其新测试传输包并清除提示。

## 8. Phase 1 实际验收结果

`scripts/run_phase1_acceptance.py` 已实际走完以下链路并输出 `PHASE 1 ACCEPTANCE: PASS`：

1. 使用 demo 账号登录。
2. 保存候选人资料、技能 JSON、当前简历及人工解析 JSON。
3. 从企业 Career 来源手工录入并收藏岗位；重复提交被 409 阻止。
4. 建立 `PLANNED` 投递；相同 `command_id` 重放命中且未重复写 Event。
5. 从 `PLANNED` 迁移到 `APPLIED`；事件数由 1 变为 2。
6. 使用旧 version 更新被 409 CAS 阻止。
7. 新增技术面试与 P1 待办；工作台聚合得到 1 个开放待办和 1 个近期面试。
8. 管理员创建第二个用户；新用户看不到 demo 用户的岗位。
9. 使用同一数据库重新创建应用；登录后仍能读取原岗位，验证 SQLite 持久化和恢复。

验收摘要：`tables=7`、`timezone=Asia/Shanghai`、`app_events=2`。

此外，已用真实 Uvicorn 进程监听 `http://127.0.0.1:8000` 并验证：

- `GET /api/health`：200，`status=ok`、`service=offerflow-api`、`timezone=Asia/Shanghai`。
- `GET /`：200，返回生产构建的 OfferFlow 前端。
- `POST /api/auth/login`：200，demo 登录成功。
- `GET /api/candidate`：200，Session 鉴权和候选人上下文成功。
- 验证后已正常关闭服务进程，没有遗留后台服务。

## 9. 当前运行方式

已在 `D:\offerflow-agent\.venv` 安装依赖，并已生成前端生产构建。直接运行：

```powershell
cd D:\offerflow-agent
.\.venv\Scripts\python.exe app.py
```

打开 `http://127.0.0.1:8000`，本地验收账号为 `demo/demo`。首次空库也会创建 `admin/admin`。这两个弱密码仅用于本地开发，实际个人长期使用前应创建自己的账号、替换 `SESSION_SECRET`，并停用或修改演示账号。

## 10. 明确未实现的边界

本阶段没有：

- LLM 或 JD/简历自动解析；
- Agent、Tool Calling 或 Career Agent 页面；
- RAG、向量库或知识治理；
- Quality、Eval、Trace 回放或 AgentOps；
- ResumeVersion、CandidateSkill、AgentMemory、PendingAction；
- 企业官网抓取、大规模采集或定时同步；
- 自动投递、自动发消息或其他外部副作用；
- heuristic_v1 岗位匹配评分（留到确有 Matching 需求的阶段实现）。

## 11. 实现过程中发现并处理的问题

1. **Windows 时区数据**：Windows Python 默认环境找不到 `Asia/Shanghai` IANA 数据。已将 `tzdata` 加入依赖，并新增“展示时区可配置、存储仍为 UTC”测试。
2. **TypeScript 7 兼容**：最初解析到 TypeScript 7，与当前 vue-tsc 不兼容。已固定为 TypeScript 5.9.3，并重新生成 `pnpm-lock.yaml`；生产构建通过。
3. **Git 初始化位置**：创建仓库时第一次 `git init` 在 `D:\` 产生了全新的空 `.git`。确认它没有 HEAD、提交或用户数据后，将该目录移动到 `D:\offerflow-agent\.git`，并把 `core.worktree` 修正为 `D:/offerflow-agent`。当前 `git rev-parse --show-toplevel` 已正确返回 `D:/offerflow-agent`，`D:\.git` 不再存在，没有删除或覆盖用户文件。
4. **开发账号安全**：空库会生成 demo/admin 弱密码，方便 MVP 首次启动。这是当前唯一需要使用者在长期运行前主动处理的配置问题，README 和本报告均已显式提示。
5. **测试依赖提示**：当前测试全绿，但 Starlette 对旧 TestClient 依赖路线给出非阻塞弃用提示；记录为后续依赖维护项，不在 Phase 1 扩展范围内。

## 12. 最终状态

Phase 1 代码、测试、生产构建、端到端验收、实际 Uvicorn 运行和报告均已完成。项目现在停在 Phase 1，不会继续 Phase 2，等待下一次明确确认。
