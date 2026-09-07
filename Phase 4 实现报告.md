# OfferFlow Phase 4 实现报告

## 1. 验收结论

Phase 4“Career Agent、确认写入与 AgentMemory”已完成，并保持 Phase 1～3 已有能力可用。

- 接入一个基于 LangChain `create_agent` 与 Qwen `ChatTongyi` 的 Career Agent。
- 固定提供 10 个业务工具；工具参数中不存在可由模型覆盖的 `candidate_id`。
- 服务端通过 ContextVar 注入当前登录候选人、账号、对话及选中的 Job/Application/Interview/Task 上下文。
- 新增 AgentMemory 与 PendingAction 两张业务表，业务库由 7 张表增至 9 张。
- 投递写入实施“提议—确认卡—结构化第二次请求—原子迁移”协议；模型自行调用确认工具不会获得授权。
- 确认执行在同一 SQLite 事务内完成 Application version CAS、状态更新、ApplicationEvent 和 PendingAction 结果落库。
- 对话接口使用 `application/x-ndjson`，前端增加真正可用的第五个主页面 Career Agent。
- 独立 `quality.db` 持久化 Run、allowlist Trace、固定评测结果与基线，不把质量数据混入业务库。
- 固定评测集 8/8 通过，隔离沙箱回放与基线一致。
- 全量自动化测试 49 项通过；Phase 1/2/3/4 验收、TypeScript 检查、Vite 生产构建与 Phase 4 发布检查通过。
- 真实 Qwen 冒烟已到达 DashScope，但当前账号返回 403 `AllocationQuota.FreeTierOnly`，即免费额度已耗尽；该项未伪装为通过。

Phase 4 完成后停止，未进入 Phase 5。

## 2. 单 Agent 与十工具目录

工具目录版本：

```text
career-tools-v1
```

Prompt 版本：

```text
career-agent-prompt-v1
```

### 2.1 读取工具

| 工具 | 作用 | 数据边界 |
|---|---|---|
| `get_candidate_360` | 获取裁剪档案、偏好、技能、对象引用和聚合计数 | 不返回姓名、邮箱、电话或简历原文 |
| `search_jobs` | 按关键词、状态、收藏、是否已投递和截止日期查询岗位 | 只查当前候选人 |
| `get_job_detail` | 获取结构化岗位、JD 和来源 | 去除不必要的 candidate_id |
| `analyze_job_match` | 返回硬条件、技能覆盖、等级和缺口 | 调用确定性 Matching，不让模型改事实 |
| `compare_jobs` | 按相同维度比较 2–5 个岗位 | 复用同一 Matching 规则 |
| `analyze_skill_gaps` | 聚合目标岗位 required/preferred 缺口与学习优先级 | 不虚构候选人已掌握技能 |
| `query_applications` | 查询投递状态及可选事件时间线 | 只查当前候选人 |
| `list_upcoming_tasks` | 查询未来时间窗口内的开放待办 | 只查当前候选人 |

岗位中心既有对比 API 继续保持 Phase 3 已验收的 2–4 个岗位限制；Phase 4 Agent 工具按确认目录支持 2–5 个岗位。两者均复用同一确定性评估函数，不存在两套打分逻辑。

### 2.2 写入控制工具

| 工具 | 风险 | 行为 |
|---|---|---|
| `propose_application_change` | CONTROLLED_WRITE | 校验状态图和 expected_version 后只创建 PendingAction；不修改 Application |
| `confirm_application_change` | CONFIRMATION_WRITE | 只有服务端确认请求注入一次性 grant 后才执行 |

模型工具 schema 不接受：

- `candidate_id`
- `actor_username`
- `confirmation_grant`
- `approved`

普通 Agent 对话中若模型主动调用 `confirm_application_change`，工具返回 `CONFIRMATION_REQUIRED`，不写业务数据；只有用户点击确认卡片触发的独立 POST 请求会由服务端生成授权。

## 3. 请求上下文与候选人隔离

每次 Agent 请求由服务端建立 `AgentRequestContext`，包含：

- 当前登录账号
- 从账号解析出的 Candidate
- chat_id
- 用户显式选中的 Job/Application/Interview/Task 引用
- sandbox 标志
- TraceRecorder
- 仅确认请求可用的一次性 confirmation grant

上下文通过 ContextVar 在工具调用链中读取。模型只能传业务查询条件或对象 ID，不能替换身份主体。Repository 仍对每个对象执行 candidate 归属查询，因此即使模型猜到其他用户的 ID，也只会得到 404。

AgentMemory 写入前进一步验证选中对象属于当前 Candidate，并验证 Job—Application—Interview—Task 之间的业务链一致性。

## 4. 数据库变化

### 4.1 业务库

业务库现在共有 9 张表：

1. `users`
2. `candidate_profiles`
3. `jobs`
4. `applications`
5. `application_events`
6. `interview_rounds`
7. `job_search_tasks`
8. `agent_memories`
9. `pending_actions`

现有 Phase 1～3 数据不需要删除或重建。`Database.initialize()` 在旧数据库启动时通过 `CREATE TABLE IF NOT EXISTS` 增加两张 Phase 4 表，并继续执行 Phase 3 的任务来源字段兼容迁移。

### 4.2 `agent_memories`

关键字段：

| 字段 | 含义 |
|---|---|
| `candidate_id + chat_id` | 每个候选人、每个对话一条当前记忆 |
| `current_job_id` | 当前岗位活引用 |
| `current_application_id` | 当前投递活引用 |
| `current_interview_id` | 当前面试活引用 |
| `current_task_id` | 当前待办活引用 |
| `last_user_goal` | 受控意图标签，不是聊天摘录 |
| `version` | 记忆更新版本 |

`last_user_goal` 只会存储“投递进度管理”“岗位检索与比较”“面试安排管理”等受控标签。即使用户把姓名、邮箱、电话或简历正文放进消息，也不会把该原文写入 AgentMemory。

### 4.3 `pending_actions`

关键字段：

| 字段 | 含义 |
|---|---|
| `action_id` | 待确认动作 ID |
| `candidate_id / actor_username / chat_id` | 候选人、操作者和对话绑定 |
| `action_type` | 当前仅 `APPLICATION_TRANSITION` |
| `payload_json` | 结构化状态迁移内容 |
| `request_hash` | 对 action_type 与 payload 的规范化 SHA-256 |
| `expected_version` | 提议时的 Application 版本 |
| `expires_at` | 确认卡过期时间，默认 15 分钟 |
| `confirmation_grant_hash` | 一次性服务端 grant 与 action/actor/request 的绑定哈希 |
| `grant_expires_at` | grant 短期有效期 |
| `status` | PENDING / EXECUTED / EXPIRED / CANCELLED / FAILED |
| `result_json` | 执行后的 allowlisted 业务结果 |

相同候选人、操作者、对话和请求哈希只产生一个动作。确认前重复提议返回原动作；重复确认已执行动作返回原结果，不产生第二条事件。

## 5. 确认式原子写入

完整链路：

```text
自然语言请求
  → Agent 调用 propose_application_change
  → 后端验证对象归属、状态图、expected_version
  → 创建 PendingAction，Application 保持不变
  → 前端显示确认卡
  → 用户点击“确认并执行”
  → 独立 POST 请求由服务端生成一次性 grant
  → confirm_application_change 读取服务端 ContextVar grant
  → BEGIN IMMEDIATE
      校验 candidate / actor / action / request_hash / expires_at / expected_version
      Application version CAS + 状态更新
      追加 AGENT_STATUS_CHANGED ApplicationEvent
      PendingAction 更新为 EXECUTED 并保存结果
    COMMIT
```

任一步失败都会回滚业务状态与事件。若用户在确认前已经手工修改 Application，旧确认卡因 version 不匹配返回 409，不能覆盖新状态。

评测 `sandbox=True` 时，`propose_application_change` 和 `confirm_application_change` 都返回未持久化结果，不写正式业务库。

## 6. NDJSON 与第五个主页面

新增页面：

```text
frontend/src/views/CareerAgentView.vue
```

页面提供：

- 多轮聊天界面
- 当前 Job/Application/Interview/Task 上下文选择
- Qwen 可用状态与工具版本
- PendingAction 确认卡、取消和确认执行
- Trace 摘要、调用工具、风险级别、状态和耗时
- 新对话与浏览器内最近消息历史

聊天历史只由当前页面向模型传递最近 12 条，不写业务库或 quality.db。

`POST /api/agent/chat/stream` 响应事件：

```text
meta → delta... → pending_action... → complete
```

响应媒体类型为 `application/x-ndjson`。前端用 `ReadableStream.getReader()` 增量解析每行 JSON。

## 7. PII allowlist Trace

质量数据使用独立 SQLite：

```text
runtime/quality.db
```

共 5 张质量表：

1. `agent_runs`
2. `trace_events`
3. `eval_runs`
4. `eval_case_results`
5. `eval_baselines`

Trace 只允许记录：

- trace/run 内部 ID、哈希化 actor/candidate/chat 引用
- run type、模型名、Prompt/Toolset/Matching 规则版本
- 工具名、风险级别、开始/结束、状态、reason code 和耗时
- allowlist 业务 ID、from/to status、expected/resulting version 和离散等级
- item/matched/missing 等计数
- 输入输出字符数、Token、首块和总耗时

Trace 不接受或持久化：

- 用户消息和 Agent 回答全文
- 隐藏推理或 Chain of Thought
- 姓名、邮箱、电话、地址
- Cookie、Token、API Key
- 简历原文、教育/经历自由文本
- 完整 JD
- 任意工具结果预览

专项测试直接读取 quality.db 的 SQL dump，验证合成姓名、邮箱、电话、简历标记、JD 标记和 `chain_of_thought` 均不存在。

## 8. 固定评测、沙箱回放与基线

评测集版本：

```text
career-agent-fixed-v1
```

固定 8 条：

1. 岗位截止过期导致硬条件拒绝
2. 毕业年份不符导致硬条件拒绝
3. required skills 全命中
4. required skills 存在明确缺口
5. 两岗位确定性对比
6. 投递查询
7. 隔离沙箱内确认后状态迁移
8. 未确认禁止业务状态写入

每次评测保存 case 结果、耗时与确定性结果哈希。首次运行创建 baseline；回放重新执行同一评测，结果哈希相同为 `MATCH`，不同为 `DRIFT`。评测实际运行在临时隔离业务库，不接触正式业务数据；Agent 工具自身另有 `sandbox` 双写阻断测试。

## 9. API 清单

### 新增

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/agent/capabilities` | 查询模型、工具数、版本、流格式和确认策略 |
| POST | `/api/agent/chat/stream` | Career Agent NDJSON 对话 |
| GET | `/api/agent/memory/{chat_id}` | 读取当前候选人的对话记忆 |
| GET | `/api/pending-actions` | 查询当前候选人的动作 |
| POST | `/api/pending-actions/{action_id}/confirm` | 结构化确认并原子执行 |
| POST | `/api/pending-actions/{action_id}/cancel` | 取消未执行动作 |

### 继续复用

- Candidate、Job、Application、Interview、Task API
- Application 状态图、ApplicationEvent、command 幂等与 version CAS
- Phase 2 Matching 与解析
- Phase 3 建议、漏斗、逾期、岗位对比和来源契约

## 10. 文件清单

### 新增

- `agent/__init__.py`
- `agent/context.py`
- `agent/tools.py`
- `agent/runner.py`
- `agent/service.py`
- `prompts/career_agent_v1.txt`
- `quality/__init__.py`
- `quality/store.py`
- `quality/trace.py`
- `quality/eval.py`
- `career/repositories/memory.py`
- `career/repositories/pending_actions.py`
- `career/services/memory.py`
- `career/services/pending_actions.py`
- `career/services/skill_gaps.py`
- `api/routers/agent.py`
- `frontend/src/views/CareerAgentView.vue`
- `tests/test_phase4.py`
- `scripts/run_phase4_acceptance.py`
- `scripts/run_phase4_live_agent_smoke.py`
- `Phase 4 实现报告.md`

### 修改

- `core/database.py`
- `core/container.py`
- `career/models.py`
- `api/main.py`
- `frontend/src/App.vue`
- `frontend/src/components/AppSidebar.vue`
- `frontend/src/api.ts`
- `frontend/src/types.ts`
- `frontend/src/styles.css`
- `frontend/package.json`
- `tests/test_phase1.py`
- `tests/test_phase2.py`
- `tests/test_phase3.py`
- `scripts/run_phase2_acceptance.py`
- `scripts/run_phase3_acceptance.py`
- `scripts/release_check.py`
- `requirements.txt`
- `.env.example`
- `Dockerfile`
- `docker-compose.yml`
- `.github/workflows/ci.yml`
- `README.md`

## 11. 自动化测试

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：

```text
49 passed, 2 warnings
```

Phase 4 新增 14 项测试，覆盖：

1. 9 张业务表与 5 张独立质量表。
2. 十工具目录完整且不接受 candidate_id。
3. Agent 工具支持 2–5 岗位对比，原 Job Center API 保持 2–4。
4. NDJSON Agent 经工具查询真实收藏未投递岗位。
5. 提议幂等且不改变 Application/Event。
6. 模型不能自行确认。
7. 前端确认后原子状态迁移、Event、version 与幂等重放。
8. 一次性 grant 只保存绑定哈希，不返回浏览器。
9. 过期确认卡不可执行。
10. 旧版本确认卡不能覆盖更新后的 Application。
11. sandbox 阻断两个写工具。
12. AgentMemory 只保存活引用与受控意图，不保存消息 PII。
13. Trace 不含 PII、CoT、简历和 JD 原文。
14. 跨候选人不能读取或确认动作；固定评测与五页面契约通过。

两个 warning：

1. FastAPI/Starlette TestClient 上游 anyio alias 弃用提示。
2. `langchain-community` 提示未来迁移到独立模型集成包；当前锁定版本已通过 Python 3.13 初始化和测试。

两者均不是本次业务失败。

## 12. 实际验收结果

### 全量测试

```text
49 passed
```

### Phase 1 回归

```text
PHASE 1 ACCEPTANCE: PASS
6/6 场景通过
```

### Phase 2 回归

```text
PHASE 2 ACCEPTANCE: PASS
6/6 场景通过
```

### Phase 3 回归

```text
PHASE 3 ACCEPTANCE: PASS
8/8 场景通过
```

### Phase 4 验收

```text
PHASE 4 ACCEPTANCE: PASS
8/8 业务场景通过
固定评测 8/8
baseline replay = MATCH
business tables = 9
tools = 10
pages = 5
```

### TypeScript 与生产构建

```text
vue-tsc --noEmit: PASS
Vite production build: PASS
31 modules transformed
CSS 17.13 kB (gzip 4.59 kB)
JS 123.08 kB (gzip 42.06 kB)
```

### 发布检查

```text
PHASE 4 RELEASE CHECK: PASS
9 business tables
5 quality tables
10 tools
confirmed writes
PII allowlist Trace
8 eval cases
5 pages
```

### 真实 Qwen 冒烟

```text
PHASE 4 LIVE AGENT SMOKE: FAIL
DashScope HTTP 403
code: AllocationQuota.FreeTierOnly
reason: Free quota exhausted
```

说明：模型适配器已初始化，并成功向 DashScope 发出请求；服务在模型执行 Tool Calling 前被供应商额度策略拒绝。没有把该结果计作真实模型通过。补充额度或在 DashScope 控制台关闭“仅使用免费额度”后，可重新运行：

```powershell
.\.venv\Scripts\python.exe scripts\run_phase4_live_agent_smoke.py
```

该脚本只使用临时合成数据库，不读写正式业务库。

## 13. 当前边界

Phase 4 未实现：

- stable/canary 模型分流
- 配置发布 generation CAS
- 完整 AgentOps 配置与监控 UI
- Phase 5 完整 Replay/Eval 管理页面
- RAG 与知识库
- ResumeVersion
- CandidateSkill 独立表
- 通用官网爬虫
- 自动登录招聘网站
- 自动投递
- 邮件发送或 HR 联系
- 自动执行面试或任务组合写入

当前写工具只覆盖 Application 状态迁移。Interview 与 Task 仍可在原有页面手工维护；未擅自扩张为自然语言多对象批量写入。

## 14. 已知问题与下一步触发条件

1. 当前 DashScope 账号额度不足，真实 Qwen 对话不可用；四个手工业务页面、Matching、建议和所有离线验收不受影响。
2. `langchain-community` 已给出未来迁移提示；在 Phase 5 升级依赖前，应评估当时可用的独立 Tongyi 集成包并重新跑固定评测，不能直接无测试换包。
3. 当前 NDJSON 在服务端完成一次 Agent 图执行后分块发送答案；工具调用、确认卡与 complete 事件遵循流协议，但没有宣称为模型逐 Token 真流式。
4. 浏览器只保留当前页面的最近消息；AgentMemory 有意不保存完整聊天。若以后确有多设备聊天历史需求，需要单独设计加密、保留期和删除策略，不能把自由文本塞进 Trace。
5. 质量评测已有持久化与基线能力，但管理 UI、P50/P95 汇总、stable/canary 和发布回滚属于 Phase 5。

---

结论：Phase 4 的 Career Agent、十工具、服务端上下文、确认式原子写入、AgentMemory、NDJSON、隐私 Trace、固定评测、沙箱回放和第五页面均已落地并通过离线完整验收。真实 Qwen 冒烟唯一阻塞为当前 DashScope 403 额度限制。现在应停止，等待确认后再进入 Phase 5。
