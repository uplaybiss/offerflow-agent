# OfferFlow Phase 5 实现报告

生成日期：2026-09-07

## 1. 验收结论

Phase 5“AgentOps 运行控制、监控与质量管理”已完成，并保持 Phase 1～4 的业务能力和边界不变。

- 新增独立 `agentops.db`，持久化不可变运行配置、当前发布状态、发布审计和幂等命令。
- 首次启动把当前环境配置固化为 `environment-baseline` stable 版本，初始 `generation=1`。
- 配置按 `DRAFT → VALIDATED → RELEASED` 流转，配置正文和 SHA-256 指纹创建后不可原地修改。
- stable/canary 发布和回滚均使用 `generation` CAS；同一 `command_id`、同一请求可以安全重试，不同请求复用命令 ID 会被拒绝。
- canary 按 `generation + candidate_id + chat_id` 做确定性哈希分流，同一代次、同一会话不会随机跳组，灰度比例限制为 `1%–50%`。
- 当前发布配置已进入真实 Agent 请求链路，动态控制模型名、重试次数、温度和历史消息条数。
- Run/Trace 增加配置版本、发布通道和发布代次，可按运行结果、类型及配置版本查询。
- AgentOps 页面提供运行数、错误率、P50/P95、Token、通道/配置分布、Trace 时间线和发布审计。
- 固定 8 条评测可以从管理页执行、更新基线并回放比较，评测夹具使用独立临时数据库，不污染正式业务数据。
- 新增仅管理员可见的第六个主页面；所有 `/api/agentops/*` 接口均在后端强制管理员鉴权。
- 全量自动化测试、Phase 1～5 验收、依赖检查、Python 编译检查、TypeScript 检查、Vite 生产构建和 Phase 5 发布检查全部通过。
- 使用当前 `.env` 中的 `qwen3.8-27b` 完成真实模型冒烟；模型实际调用 `search_jobs`，且返回值与 Trace 中的 stable 配置、channel 和 generation 一致。

## 2. Phase 5 边界

本阶段只建设单机版 AgentOps 控制面及质量管理，不改变 9 张业务表，也没有提前实现以下能力：

- RAG 与知识库
- `ResumeVersion`
- `CandidateSkill` 独立表
- 官网大规模抓取
- 自动登录或自动投递
- 邮件发送或 HR 联系
- 分布式配置中心、跨实例一致性和生产级流量网关

固定评测回放是隔离夹具上的确定性回归，不是任意历史聊天重放。系统继续不保存聊天全文、完整简历或完整 JD，因此不能在不改变隐私边界的前提下重建任意历史模型请求。

## 3. 总体结构

```text
管理员 AgentOps 页面
  ├─ 不可变配置：创建 → 校验 → stable/canary 发布 → 回滚
  ├─ generation CAS + command_id 幂等
  ├─ Run 指标、Trace 列表/详情、发布审计
  └─ 固定评测 → 基线更新 → 隔离回放比较

Agent 请求
  → 解析当前 candidate_id + chat_id
  → 读取当前 release generation
  → 确定性选择 stable/canary 配置
  → 以选中配置构造/复用 Agent 图
  → 执行 Tool Calling
  → 将 config_version/channel/generation 写入 Run 与 Trace
```

控制面、质量面和业务面分别使用三个 SQLite WAL 数据库：

```text
runtime/offerflow.db   业务数据（9 表）
runtime/quality.db     Run、Trace、评测与基线（5 表）
runtime/agentops.db    配置、发布、审计与幂等命令（4 表）
```

## 4. AgentOps 数据库

### 4.1 `agent_config_versions`

| 字段 | 含义 |
|---|---|
| `version_id` | 不可变配置版本 ID |
| `label` | 管理员填写的版本标签 |
| `status` | `DRAFT / VALIDATED / RELEASED` |
| `settings_json` | 允许发布的运行参数 |
| `settings_sha256` | 配置正文的确定性指纹 |
| `validation_json` | 校验结果及错误列表 |
| `revision` | 草稿校验使用的 revision CAS |
| `created_by_ref` | 哈希化操作者引用 |
| `created_at / validated_at` | UTC 审计时间 |

创建后没有配置更新 API。若需要调整参数，必须创建新版本；状态和校验信息可以按受控流程变化，但 `settings_json` 不被原地覆盖。

允许的配置项只有：

```text
model_name
max_retries          0..5
temperature          0..1
history_messages     1..20
prompt_version
toolset_version
rule_version
```

当前代码只允许校验与代码实际加载的 Prompt、工具目录和 Matching 规则版本，避免发布数据库中声明存在、进程实际并未加载的版本。

### 4.2 `agent_release_state`

单行发布指针，保存：

- stable 配置版本
- 可选 canary 配置版本
- canary 百分比
- 当前 `generation`
- 哈希化操作者与更新时间

每次发布或回滚都要求客户端提交当前 `expected_generation`。数据库在 `BEGIN IMMEDIATE` 事务内再次比较 generation，并以 `WHERE generation = ?` 更新；并发或过期操作返回 409，不能静默覆盖新版本。

### 4.3 `agent_release_audit`

记录环境基线、配置校验、stable 发布、canary 发布和回滚事件，包括代次、版本、哈希化操作者、受控详情及 UTC 时间。

### 4.4 `agentops_commands`

保存 `command_id + scope + payload_hash + result_json`。行为如下：

- 相同命令 ID、相同 scope、相同 payload：返回第一次结果，并标记 `idempotent_replay=true`。
- 相同命令 ID 被用于不同操作或不同 payload：返回 409。
- generation CAS、发布状态更新、审计事件和命令结果在同一事务内提交。

## 5. stable/canary 与回滚

canary 选择使用：

```text
bucket = SHA-256("generation:candidate_id:chat_id") 的前 12 位 mod 10000
进入 canary 当 bucket < canary_percent × 100
```

它具备以下性质：

- 同一 generation、同一候选人会话选择稳定。
- 不依赖进程内随机数，服务重启后结果不变。
- 新发布产生新 generation，因此会重新划分样本。
- 灰度比例被限制在 50% 以内，stable 始终保留主流量。

发布 stable 会把目标版本设为 stable 并清空 canary；发布 canary 保留现有 stable。回滚把目标已验证/已发布版本恢复为 stable、清空 canary，并产生新 generation。回滚只影响后续 Agent 运行配置，不会回滚岗位、投递、面试或待办数据。

## 6. Agent 运行链路接入

每次聊天前，`CareerAgentService` 使用服务端解析出的 Candidate 和请求 `chat_id` 选择配置，不接受模型提交身份或通道。选中的设置传给 `LangChainAgentRunner`：

- `model_name`
- `max_retries`
- `temperature`
- `history_messages`

Runner 按有效模型配置缓存 Agent 图；配置变化会使用不同缓存键，不需要重启进程才能切换模型运行参数。

以下版本字段同时写入 NDJSON `complete.runtime` 和持久化 Trace：

```text
config_version_id
release_channel
release_generation
```

Prompt、工具目录和规则版本仍写入 Run。这样可以回答“哪次请求用了哪个配置、属于哪个发布通道、发生在哪一代”。

## 7. 监控与 Trace

`quality.db` 的 `agent_runs` 新增：

- `config_version_id`
- `release_channel`
- `release_generation`

评测表新增运行模式、结果哈希、基线状态、配置版本及 case 分类。初始化采用兼容迁移：旧数据库缺列时执行 `ALTER TABLE ADD COLUMN`，不会删除或重建现有表。

运行概览支持 1～1440 分钟窗口，并计算：

- Run 数、失败数、错误率
- 总耗时 P50/P95
- 首块耗时 P50/P95
- 输入/输出 Token 合计
- stable/canary 通道分布
- 配置版本分布

百分位基于窗口内已完成 Run。样本很少时只代表当前样本，不包装为长期性能结论。由于项目没有维护带生效时间的模型价格目录，成本字段明确返回 `null`，不根据 Token 猜测费用。

Trace 详情继续遵守 Phase 4 allowlist：不保存用户消息、Agent 回答、CoT、Cookie、API Key、完整简历或完整 JD。API Key 与 Base URL 仍只来自进程环境，不进入运行配置数据库。

## 8. 固定评测与基线回放

评测套件版本：

```text
career-agent-fixed-v1
```

固定 8 条场景：

| Case | 分类 | 验证内容 |
|---|---|---|
| `hard_deadline_reject` | hard_condition | 岗位过期必须触发硬条件拒绝 |
| `hard_graduation_reject` | hard_condition | 届别不符必须触发硬条件拒绝 |
| `required_skill_full_match` | skill_match | required skill 全命中 |
| `required_skill_gap` | skill_match | required skill 缺口可解释 |
| `compare_jobs` | read_tool | 同维度比较两个岗位 |
| `query_applications` | read_tool | 查询真实投递数据 |
| `confirmed_transition` | write_control | 确认后状态迁移被持久化 |
| `unconfirmed_write_blocked` | write_control | 未确认写入不改变 Application |

每次执行都新建临时业务库、质量库和 AgentOps 库，使用确定性夹具与离线 Runner，不调用外部模型，也不读取正式数据库。评测只保存 allowlist actual 字段。基线通过规范化结果计算 SHA-256：相同为 `MATCH`，不同为 `DRIFT`；管理员可以显式创建或更新基线。

## 9. AgentOps API

以下 12 个接口全部要求管理员身份：

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/agentops/overview` | 发布状态、版本、指标、Trace、评测与审计总览 |
| GET | `/api/agentops/configurations` | 配置版本列表 |
| POST | `/api/agentops/configurations` | 创建不可变草稿 |
| POST | `/api/agentops/configurations/{version_id}/validate` | revision CAS 校验草稿 |
| POST | `/api/agentops/releases` | 发布 stable/canary |
| POST | `/api/agentops/rollback` | 回滚到指定版本 |
| GET | `/api/agentops/traces` | 按状态、类型、配置筛选 Run |
| GET | `/api/agentops/traces/{trace_id}` | Trace 详情与事件时间线 |
| GET | `/api/agentops/evaluations` | 评测运行列表 |
| POST | `/api/agentops/evaluations/run` | 执行固定评测，可显式更新基线 |
| POST | `/api/agentops/evaluations/replay` | 回放并比较基线 |
| GET | `/api/agentops/evaluations/{eval_run_id}` | 评测及 8 条 case 详情 |

评测详情按 ID 直接查询，不受最近 200 条列表分页限制。

## 10. 第六个主页面

新增：

```text
frontend/src/views/AgentOpsView.vue
```

页面包含：

- 当前 generation 与 stable/canary 双通道
- Run、错误率、P50/P95、Token 指标卡
- 配置草稿创建与显式校验
- stable/canary 发布、灰度比例和回滚
- 固定评测、基线更新与回放
- 最近 Run、配置版本、发布通道及耗时
- Trace 事件时间线
- 评测运行及逐 case 结果

侧边栏根据登录账号角色过滤该页面。即使绕过前端直接请求，后端 `admin_user` 依赖仍会拒绝普通用户。

## 11. 文件清单

### 11.1 新增

```text
agentops/__init__.py
agentops/store.py
agentops/service.py
api/routers/agentops.py
quality/management.py
quality/scenarios.py
frontend/src/views/AgentOpsView.vue
scripts/run_phase5_acceptance.py
scripts/run_phase5_live_agent_smoke.py
tests/test_phase5.py
Phase 5 实现报告.md
```

### 11.2 主要修改

```text
agent/runner.py
agent/service.py
api/main.py
api/routers/agent.py
core/container.py
quality/__init__.py
quality/eval.py
quality/store.py
quality/trace.py
frontend/src/App.vue
frontend/src/components/AppSidebar.vue
frontend/src/types.ts
frontend/src/styles.css
frontend/package.json
.env.example
docker-compose.yml
.github/workflows/ci.yml
README.md
scripts/release_check.py
scripts/run_phase4_acceptance.py
tests/test_phase1.py
tests/test_phase2.py
tests/test_phase3.py
tests/test_phase4.py
```

Phase 4 验收中的假 Runner 接口增加可选 `runtime_config`，用于验证 Phase 5 动态配置接入，同时保持旧场景行为不变。

## 12. 实际验收场景

`scripts/run_phase5_acceptance.py` 实际完成：

1. 从环境创建无密钥、不可篡改的 stable baseline，generation 为 1。
2. 创建草稿并使用 revision CAS 显式校验。
3. 发布 25% canary，generation 从 1 变为 2。
4. 重试同一命令得到幂等结果；旧 generation 和复用不同 payload 均被拒绝。
5. 找到 stable 与 canary 两类确定性 cohort，并分别执行真实 HTTP Agent 请求。
6. 验证选中配置进入 Runner、NDJSON runtime 和持久化 Trace。
7. 验证 Run、错误率、P50/P95、Token 和通道/配置统计。
8. 通过管理 API 执行固定评测 8/8、建立基线并回放得到 `MATCH`。
9. 回滚原 stable，generation 从 2 变为 3，并清空 canary。
10. 验证普通用户访问 AgentOps 返回 403、页面总数为 6、业务表仍为 9。

最终验收摘要：

```text
PHASE 5 ACCEPTANCE: PASS
eval=8/8
replay=MATCH
generations=1 -> 2 -> 3
channels=stable + canary
pages=6
```

## 13. 测试与构建结果

### 13.1 自动化测试

```text
python -m pytest -q
58 passed
```

Phase 5 新增覆盖：

- 控制面 4 表、环境基线、无密钥持久化
- 管理员权限
- 不可提前发布 DRAFT
- revision CAS、generation CAS 和命令幂等
- canary 上限与确定性分流
- 发布配置进入 Runner 和 Trace
- Trace 隐私 allowlist
- P50/P95、错误率、Token、通道与配置统计
- 固定评测 8/8、基线和回放 `MATCH`
- 评测详情不受列表分页限制
- 第六页面与延后模块边界

唯一警告来自 Starlette `TestClient` 对 AnyIO 旧别名的依赖弃用提示，不是业务失败。

### 13.2 历史阶段验收

```text
Phase 1 acceptance: PASS
Phase 2 acceptance: PASS
Phase 3 acceptance: PASS
Phase 4 acceptance: PASS（8/8 固定评测，5 个 Phase 4 页面）
Phase 5 acceptance: PASS（8/8，replay=MATCH，6 个当前页面）
```

Phase 4 脚本输出 `pages=5` 是对 Phase 4 历史边界的回归断言；当前应用由 Phase 5 验收确认是 6 个页面。

### 13.3 静态检查、构建与发布检查

```text
pip check: No broken requirements found
python -m compileall: PASS
vue-tsc --noEmit: PASS
Vite production build: PASS（33 modules transformed）
Phase 5 release check: PASS
```

发布检查确认：

```text
9 business tables
5 quality tables
4 AgentOps tables
10 Agent tools
stable/canary + generation CAS
PII allowlist Trace
8 eval cases
6 pages
```

### 13.4 真实模型冒烟

使用独立临时数据库和合成岗位执行，不读取或修改正式业务库：

```text
PHASE 5 LIVE AGENT SMOKE: PASS
model=qwen3.8-27b
tool=search_jobs
channel=STABLE
generation=1
```

这项测试同时验证了 OpenAI-compatible DashScope 接口、真实 Tool Calling、运行配置选择和 Trace 版本关联。

## 14. 配置与部署更新

新增环境变量：

```text
OFFERFLOW_AGENTOPS_DB_PATH=runtime/agentops.db
AGENT_HISTORY_MESSAGES=12
```

Docker Compose 把 `agentops.db` 与另外两个数据库一起挂载到 `/data`。CI 更新为 Phase 5，除全量 pytest 和生产构建外，增加 Phase 5 验收与独立 TypeScript 检查。

## 15. 当前已知限制与后续注意事项

1. 当前是本地单进程控制面。SQLite 事务足以覆盖本项目部署方式，但不等同于多实例分布式配置中心。
2. 配置版本记录参数与版本指纹，不打包 Prompt/工具代码制品；代码部署和配置发布仍需保持配套。
3. 固定评测故意不调用外部模型，适合验证确定性业务链路，不覆盖模型回答质量漂移。
4. 任意历史对话回放需要保存原始输入，这与当前隐私边界冲突，因此没有实现。
5. P50/P95 在低样本窗口中统计意义有限；成本因缺少时效性价格目录而不估算。
6. 回滚只影响后续请求；已经开始的请求不会被中断，也不会回滚业务数据。
7. 本地默认账号仅供开发，公开部署前必须更换 `demo/demo`、`admin/admin` 和 `SESSION_SECRET`。

Phase 5 已在确认边界内完成。未继续扩展新的业务阶段。
