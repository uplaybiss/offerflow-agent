# OfferFlow Phase 3 实现报告

## 1. 验收结论

Phase 3“投递与面试效率增强”已完成，并保持 Phase 1、Phase 2 功能可用。

- 根据岗位截止日期、测评时间和面试时间生成可追溯建议任务。
- 建议只在用户点击“保留为待办”后写入数据库。
- 使用稳定 `suggestion_key` 和唯一索引保证重复确认不会生成重复任务。
- 保留后的建议任务与手工任务一样可编辑、完成和取消，同时保留来源与规则快照。
- 工作台增加投递漏斗、30 天内近期面试、逾期待办和建议任务视图。
- 岗位中心增加 2–4 岗对比和完整岗位编辑。
- 增加 `source_adapter_v1` 单条岗位更新预览契约；来源不可用或执行失败时原岗位不变。
- 数据库仍为 7 张表，前端仍为 4 个主页面。
- 自动化测试 35 项全部通过，Phase 1/2/3 验收、TypeScript 检查、Vite 生产构建和发布检查全部通过。

Phase 3 完成后停止，未进入 Phase 4。

## 2. 建议任务设计

### 2.1 生成规则

规则版本固定为：

```text
task_suggestion_v1
```

当前生成三类建议：

| 来源 | 生成条件 | 默认任务类型 | 默认优先级 |
|---|---|---|---|
| `JOB_DEADLINE` | ACTIVE 岗位有截止日期，且尚未投递或仍为 PLANNED | APPLICATION | 7 天内 P1，否则 P2 |
| `ASSESSMENT_TIME` | ASSESSMENT 轮次状态为 SCHEDULED 且在配置窗口内 | ASSESSMENT | P1 |
| `INTERVIEW_TIME` | 非测评面试轮次状态为 SCHEDULED 且在配置窗口内 | INTERVIEW | P1 |

可配置窗口：

```text
SUGGESTION_JOB_HORIZON_DAYS=45
SUGGESTION_JOB_LEAD_DAYS=3
SUGGESTION_EVENT_HORIZON_DAYS=30
SUGGESTION_EVENT_LEAD_HOURS=24
WORKBENCH_INTERVIEW_HORIZON_DAYS=30
```

### 2.2 预览与确认

`GET /api/task-suggestions` 每次根据当前正式数据计算临时建议，返回：

- `suggestion_key`
- 来源类型、来源对象 ID 和事件时间
- 待办预览
- 规则版本、具体规则和输入快照
- `persisted=false`
- `requires_confirmation=true`

此接口不写数据库。用户调用接受接口后才创建正式待办。

### 2.3 去重与追溯

`suggestion_key` 由以下信息确定性计算：

```text
task_suggestion_v1 + source_type + source_id
```

同一岗位截止或同一面试轮次始终得到同一个 key。数据库增加局部唯一索引：

```text
UNIQUE(candidate_id, suggestion_key) WHERE suggestion_key <> ''
```

服务层在创建前检查，数据库层防止并发重复。重复接受返回原任务并标记 `idempotent_replay=true`。

保留后的任务记录：

- `origin=SUGGESTED`
- `suggestion_key`
- `suggestion_source`
- `suggestion_payload`：来源快照与规则 Trace

用户修改标题、说明、时间、类型、优先级或状态时，来源字段不会丢失。

## 3. 数据库变化

没有新增业务表，仍为：

1. `users`
2. `candidate_profiles`
3. `jobs`
4. `applications`
5. `application_events`
6. `interview_rounds`
7. `job_search_tasks`

仅为 `job_search_tasks` 增加四个来源追踪字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `origin` | TEXT | `MANUAL` 或 `SUGGESTED` |
| `suggestion_key` | TEXT | 确定性去重键 |
| `suggestion_source` | TEXT | `JOB_DEADLINE`、`ASSESSMENT_TIME` 或 `INTERVIEW_TIME` |
| `suggestion_payload_json` | TEXT | 来源对象和规则输入快照 |

`Database.initialize()` 包含兼容 Phase 1/2 现有数据库的增量迁移：启动时检查 `PRAGMA table_info`，只补充缺少字段，再建立唯一索引。迁移测试已覆盖旧表结构，不要求删除或重建用户数据。

## 4. 工作台增强

### 4.1 投递漏斗

当前漏斗展示以下 Application 当前状态分布：

- PLANNED
- APPLIED
- ASSESSMENT
- INTERVIEW
- OFFER

REJECTED 与 WITHDRAWN 作为结果单独展示。这里是当前状态分布，不包装成严格的阶段转化率。

### 4.2 近期面试

仅展示：

- 状态为 `SCHEDULED`
- 时间晚于当前时间
- 位于 `WORKBENCH_INTERVIEW_HORIZON_DAYS` 窗口内

默认窗口为 30 天，按时间升序展示。

### 4.3 逾期待办

满足以下条件时进入逾期视图：

- 状态为 `TODO` 或 `IN_PROGRESS`
- `due_at` 已设置
- `due_at < 当前 UTC 时间`

逾期待办可直接进入原有编辑表单，不产生新的任务模型。

## 5. 岗位对比

新增确定性对比接口：

```text
POST /api/jobs/compare
```

请求一次选择 2–4 个不同岗位。响应按用户选择顺序返回：

- 公司、岗位、地点、用工类型、截止日期和来源
- Job effective status
- heuristic 版本与免责声明
- 匹配等级
- required skill coverage
- critical/other skill gaps
- 完整确定性 MatchResult

对比复用 Phase 2 Matching，不增加第二套打分逻辑。同样输入和同样 heuristic 配置返回相同结果；岗位仍受候选人数据隔离保护。

## 6. 企业招聘来源契约

### 6.1 已有来源字段

继续使用：

- `source_type`
- `source_name`
- `source_url`
- `external_job_id`
- `company_career_url`
- `source_metadata.source_contract.adapter_key`
- `source_metadata.source_contract.source_company_id`

没有为不确定的网站结构提前增加新表。

### 6.2 Adapter 接口

契约版本：

```text
source_adapter_v1
```

适配器仅需提供：

```python
key: str
display_name: str
fetch_job(job: dict) -> dict
```

Phase 3 默认不安装任何企业适配器，不执行通用抓取。

### 6.3 单条来源更新

```text
GET  /api/sources/capabilities
POST /api/jobs/{job_id}/source-refresh
```

更新接口可能返回：

- `NOT_APPLICABLE`：不是企业官网来源
- `UNAVAILABLE`：未安装对应适配器
- `ERROR`：适配器执行失败
- `PREVIEW`：生成可编辑更新预览

无论哪种状态，刷新接口都不直接写 Job。只有用户校对并调用现有 `PATCH /api/jobs/{job_id}` 后才更新正式岗位。

适配器缺失或报错时返回可读状态，`job_unchanged=true`，不会让岗位、投递、面试和待办接口失败。

## 7. API 清单

### 新增

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/task-suggestions` | 计算待确认建议任务 |
| POST | `/api/task-suggestions/{suggestion_key}/accept` | 幂等保留为正式待办 |
| POST | `/api/jobs/compare` | 对比 2–4 个岗位 |
| GET | `/api/sources/capabilities` | 查询来源适配器契约与可用适配器 |
| POST | `/api/jobs/{job_id}/source-refresh` | 生成单条岗位来源更新预览 |

### 复用并增强

- `GET /api/workbench`：增加漏斗、近期面试、逾期待办。
- `GET /api/tasks`：返回任务来源追踪字段。
- `PATCH /api/tasks/{task_id}`：建议任务保留后仍可编辑。
- `PATCH /api/jobs/{job_id}`：确认来源预览或进行任意手工修正。

## 8. 文件清单

### 新增

- `career/services/suggestions.py`
- `career/services/sources.py`
- `sources/__init__.py`
- `sources/adapters.py`
- `api/routers/suggestions.py`
- `api/routers/sources.py`
- `tests/test_phase3.py`
- `scripts/run_phase3_acceptance.py`
- `Phase 3 实现报告.md`

### 修改

- `core/database.py`
- `career/repositories/tasks.py`
- `career/services/tasks.py`
- `core/container.py`
- `api/main.py`
- `api/routers/matching.py`
- `matching/service.py`
- `frontend/src/types.ts`
- `frontend/src/views/WorkbenchView.vue`
- `frontend/src/views/JobCenterView.vue`
- `frontend/src/views/LoginView.vue`
- `frontend/src/styles.css`
- `frontend/package.json`
- `.env.example`
- `scripts/release_check.py`
- `README.md`

## 9. 自动化测试

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：

```text
35 passed, 2 warnings
```

Phase 3 新增 9 项测试：

1. Phase 2 旧数据库无损增加任务来源字段，业务表仍为 7 张。
2. 同时生成岗位截止、测评和面试三类可追溯建议，确认前任务表为空。
3. 建议重复确认幂等，数据库只有一条任务，保留后仍可编辑。
4. 已投递岗位不再生成投递截止建议。
5. 工作台漏斗、近期面试和逾期待办聚合正确。
6. 岗位对比确定可复现、参数限制正确且候选人隔离有效。
7. 来源适配器缺失或报错时原岗位完全不变。
8. 可用适配器只生成白名单更新预览，用户 PATCH 后才保存，之后仍可手工修正。
9. 前端仍为四页面，并包含建议、漏斗、逾期、对比、来源刷新和岗位编辑契约。

两个 warning 来自 FastAPI/Starlette TestClient 上游弃用提示，不是业务失败。

## 10. 实际验收结果

### 全量测试

```text
35 passed
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

### Phase 3 验收

```text
PHASE 3 ACCEPTANCE: PASS
8/8 场景通过
suggestions=3, tasks=2, tables=7
```

Phase 3 验收实际走通：

1. 创建企业官网来源岗位和 PLANNED 投递。
2. 创建一场在线测评和一场技术面试。
3. 得到三条未持久化建议。
4. 同一建议连续接受两次，只保留一条任务。
5. 手工修改建议任务。
6. 创建逾期待办并查看漏斗、近期面试、逾期聚合。
7. 对比两个岗位。
8. 在适配器不可用时确认岗位不变，再手工更新岗位。

### TypeScript 与生产构建

```text
vue-tsc --noEmit: PASS
Vite production build: PASS
29 modules transformed
CSS 15.24 kB (gzip 4.19 kB)
JS 115.53 kB (gzip 39.79 kB)
```

### 发布检查

```text
PHASE 3 RELEASE CHECK: PASS
7 tables
traceable idempotent suggestions
funnel/interview/overdue views
job comparison
optional source contract
4 pages
```

## 11. 手工数据可编辑性

Phase 3 没有让建议或外部来源接管正式数据：

- 用户可以忽略建议，不产生数据库记录。
- 建议保留后可修改、完成或取消。
- 来源刷新只生成预览。
- 来源适配器失败不改变 Job。
- 用户始终可通过岗位编辑表单修改公司、标题、地点、状态、时间、技能、JD 和来源字段。
- 所有正式更新继续使用 `version` CAS，避免覆盖并发修改。

## 12. 当前边界

Phase 3 未实现：

- 通用爬虫
- 自动登录招聘网站
- 自动投递
- 邮件发送
- HR 联系
- Career Agent 与工具编排
- PendingAction
- AgentMemory
- RAG
- Quality/AgentOps
- ResumeVersion
- CandidateSkill 独立表
- 第五个主页面

## 13. 已知问题

1. 默认没有安装任何企业官网适配器；这属于 Phase 3 有意边界。只有用户明确具体企业和范围后才应实现小规模 adapter。
2. 建议任务是确定性规则，不会读取邮件或招聘网站，因此测评/面试时间必须先由用户记录到 InterviewRound。
3. 已保留后又取消的建议不会再次生成，以避免重复骚扰；用户可以继续编辑或恢复原任务状态。
4. 投递漏斗展示当前状态分布，不宣称为历史阶段转化率。
5. Phase 2 已知的 DashScope 密钥 401 问题不属于 Phase 3；不影响建议、对比、工作台或手工维护。

---

结论：Phase 3 代码、迁移、自动化测试、三阶段回归验收、前端生产构建和发布边界均已完成。当前应停止，等待确认后再进入 Phase 4。
