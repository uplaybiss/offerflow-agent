# OfferFlow Agent《Phase 1.1 修复报告》

修复日期：2026-09-07
项目目录：`D:\offerflow-agent`
结论：**六项 Phase 1.1 Bugfix 已完成并通过回归验证；项目已停止，未进入 Phase 2。**

## 1. 修复范围

本次只修复 Phase 1 已有模型和页面中的正确性、完整性问题：

1. 限制 Application 普通创建的初始状态。
2. 强制 Task 所关联的 Job、Application、Interview 属于同一业务链。
3. 使 EXPIRED 筛选包含按截止日期计算出的过期岗位。
4. 在 Job Center 补齐后端既有的三个 Phase 1 字段。
5. 在前端接通已有 Task/Interview PATCH 维护能力。
6. 修复 Job Center 的嵌套 button 无效 HTML。

没有增加数据表、数据库字段、API 路径或领域模块，也没有实现任何 Phase 2～5 功能。

## 2. 修改文件

### 后端

- `career/state_machine.py`
  - `validate_initial_application_status` 仅允许 `PLANNED`、`APPLIED`。
- `career/services/applications.py`
  - Application 列表筛选继续接受全部合法状态，避免初始状态校验收紧后误伤查询。
- `career/repositories/tasks.py`
  - 在对象归属校验之外，增加 Job/Application/Interview 业务链一致性校验。
- `career/repositories/jobs.py`
  - 增加基于当前业务日期的 `ACTIVE`/`EXPIRED` 有效状态查询条件。
- `career/services/jobs.py`
  - 将配置时区下的当前本地日期传给 Repository，保证展示与筛选口径一致。

### 前端

- `frontend/src/views/JobCenterView.vue`
  - 补充 `employment_type`、`recruitment_cycle`、`graduation_year` 的录入和详情展示。
  - 将岗位行改为普通容器，岗位选择 button 与收藏 button 作为两个同级控件，不再互相嵌套。
- `frontend/src/views/WorkbenchView.vue`
  - 待办增加编辑表单、完成和取消操作，全部调用原 `PATCH /api/tasks/{task_id}`。
- `frontend/src/views/ApplicationTrackerView.vue`
  - 面试增加编辑、改期、状态修改、完成、取消、结果及备注维护，全部调用原 `PATCH /api/interviews/{round_id}`。
- `frontend/src/types.ts`
  - 补齐前端已使用的 Job 和 Task 既有字段类型。
- `frontend/src/api.ts`
  - 增加 UTC 时间转换为配置时区 `datetime-local` 输入值的辅助函数，避免编辑时间时发生偏移。
- `frontend/src/styles.css`
  - 增加行操作、内联编辑器和岗位行焦点样式。

### 测试与报告

- `tests/test_phase1.py`
  - 新增六组 Phase 1.1 回归测试，并扩展已有测试数据中的三个岗位字段。
- `Phase 1.1 修复报告.md`
  - 本报告。

## 3. Bug 1：Application 初始状态绕过

### 修复前复现

对任一尚未建立投递的 `job_id` 调用：

```http
POST /api/applications
{
  "job_id": "JOB-...",
  "status": "OFFER",
  "command_id": "create:bypass-001"
}
```

原 `validate_initial_application_status` 以整个 `ApplicationStatus` 枚举为允许集合，因此请求可直接创建 `OFFER`，不经过 `PLANNED/APPLIED` 及迁移图。

### 修复方式

普通创建接口的允许集合固定为：

```text
PLANNED, APPLIED
```

`ASSESSMENT`、`INTERVIEW`、`OFFER`、`REJECTED`、`WITHDRAWN` 必须由已有 Application 经 `/transitions` 按迁移图进入。非法普通创建现在返回 HTTP 400。

同时将 Application 列表的状态校验与“初始状态校验”解耦，因此 `GET /api/applications?status=OFFER` 等合法查询不受影响。

### 新增测试

`test_application_create_rejects_all_non_initial_states`：逐一验证直接创建以下五个状态全部返回 400：

- `ASSESSMENT`
- `INTERVIEW`
- `OFFER`
- `REJECTED`
- `WITHDRAWN`

并验证普通创建 `APPLIED` 仍成功。

## 4. Bug 2：Task 跨对象关联不一致

### 修复前复现

先为岗位 A、岗位 B 分别建立投递 A、投递 B 及面试 A、面试 B，再提交：

```http
POST /api/tasks
{
  "job_id": "岗位 A",
  "application_id": "投递 B",
  "interview_round_id": "面试 B",
  "title": "准备面试",
  "status": "TODO"
}
```

旧实现只分别检查三个对象是否属于当前 Candidate，因此可能把不同岗位链上的合法对象拼到同一个 Task。

### 修复方式

`TaskRepository._validate_links` 现在在同一事务内完成两层校验：

1. 每个对象存在且属于当前 Candidate。
2. 所有同时提供的对象必须满足：
   - `application.job_id == job_id`
   - `interview.application_id == application_id`
   - 即使没有显式提供 application_id，`interview` 所属 Application 的 `job_id` 也必须等于提供的 job_id。

创建和更新均复用同一校验。不一致返回 HTTP 400；不存在或不属于当前 Candidate 仍返回 404。

### 新增测试

`test_task_rejects_cross_chain_job_application_and_interview_links` 验证：

- Job A + Application B 被拒绝。
- Application A + Interview B 被拒绝。
- Job A + Interview B 被拒绝。
- Job A + Application A + Interview B 被拒绝。
- Job A + Application A + Interview A 成功。
- 已创建 Task 更新为不一致 Job/Application 组合也被拒绝。

## 5. Bug 3：effective_status=EXPIRED 无法筛选

### 修复前复现

数据库保存一个 `status=ACTIVE`、`deadline` 早于当前本地日期的岗位：

- 普通岗位列表返回 `effective_status=EXPIRED`。
- `GET /api/jobs?status=EXPIRED` 却只执行 `WHERE status='EXPIRED'`，因此查不到该岗位。

### 修复方式

筛选 `EXPIRED` 时使用：

```sql
status = 'EXPIRED'
OR (status = 'ACTIVE' AND deadline <> '' AND deadline < :local_today)
```

筛选 `ACTIVE` 时相应排除按截止日已经过期的记录。`:local_today` 来自 `APP_TIMEZONE` 配置下的当前日期，和 API 返回的 `effective_status` 使用同一判断口径；截止日当天仍视为 ACTIVE。

### 新增测试

`test_expired_filter_includes_explicit_and_effective_expiration` 同时创建：

- ACTIVE + 过往截止日；
- 显式 EXPIRED + 未来截止日；
- ACTIVE + 未来截止日。

验证 `status=EXPIRED` 精确返回前两条，不返回第三条。

## 6. Bug 4：Job Center 缺少三个既有字段

### 修复前复现

打开 Job Center 的“新增岗位”和岗位详情，后端 `jobs` 表及 API 已支持以下字段，但页面没有录入或展示入口：

- `employment_type`
- `recruitment_cycle`
- `graduation_year`

手工沉淀真实岗位时容易丢失 Phase 2 Matching 需要的基础事实。

### 修复方式

在新增岗位表单增加“用工类型、招聘批次、毕业年份”，并在详情面板原样展示。字段仍使用原 API 与原数据库列，没有新增 Schema。

### 新增测试

前端契约测试同时检查三个字段在录入模型和详情模型中均存在；通用 Job API 测试数据也开始携带这三个字段。

## 7. Bug 5：已有 PATCH 能力没有前端入口

### 修复前复现

- Workbench 只能新增或完成待办，不能编辑内容、优先级、类型和截止时间，也不能取消。
- 投递详情只能新增面试轮次，不能改期、修改状态、完成、取消或记录结果。
- 后端相应 PATCH API 已存在，因此问题属于前端能力缺口。

### 修复方式

待办：

- 增加内联编辑表单，可修改标题、说明、类型、优先级和截止时间。
- 增加“完成”和“取消”操作。
- 保留 Job/Application/Interview 原关联，并携带当前 version 执行 CAS 更新。

面试：

- 增加编辑表单，可修改标题、类型、时间、状态、备注和结果。
- 增加“完成”和“取消”快捷操作。
- UTC 时间在进入 `datetime-local` 编辑框前按 `APP_TIMEZONE` 转换，提交后继续由后端规范化为 UTC。
- 所有操作均使用既有 PATCH API 和 version CAS。

### 新增测试

- `test_task_patch_supports_edit_and_cancel`：验证编辑内容/优先级/状态后再取消。
- `test_interview_patch_supports_reschedule_complete_cancel_and_result`：验证改期、完成、结果记录，并验证另一轮面试可取消。
- 前端契约测试验证 Task/Interview 的编辑、完成、取消和结果入口存在。

## 8. Bug 6：JobCenter 嵌套 button

### 修复前复现

岗位列表每行原本是外层 `<button class="job-row">`，内部又包含收藏 `<button class="star">`，属于无效 HTML。浏览器可能自动修正 DOM，造成点击、键盘焦点或事件冒泡表现不一致。

### 修复方式

岗位行改为普通容器，两个操作按钮互为同级：

```html
<div class="job-row">
  <button class="star">...</button>
  <button class="job-select">...</button>
</div>
```

岗位选择按钮和收藏按钮都保留原有鼠标及键盘能力，不再存在任何交互控件嵌套。

### 新增测试

前端契约测试确认 JobCenter 不再出现岗位行外层 button，同时保留 `job-row` 交互结构。

## 9. 新增测试汇总

本次在原 9 项测试基础上新增 6 项：

1. `test_application_create_rejects_all_non_initial_states`
2. `test_task_rejects_cross_chain_job_application_and_interview_links`
3. `test_expired_filter_includes_explicit_and_effective_expiration`
4. `test_task_patch_supports_edit_and_cancel`
5. `test_interview_patch_supports_reschedule_complete_cancel_and_result`
6. `test_frontend_phase11_maintenance_and_valid_job_row_contracts`

最终自动化测试总数：**15 项**。

## 10. 最终验证结果

按要求分别执行：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_phase1_acceptance.py
.\.venv\Scripts\python.exe scripts\release_check.py
corepack pnpm --dir frontend exec vue-tsc --noEmit
corepack pnpm --dir frontend exec vite build
```

结果：

- pytest：**15 passed**，耗时 11.04 秒。
- Phase 1 acceptance：**PASS**；六段 MVP 链路全部通过，`tables=7`、`timezone=Asia/Shanghai`、`app_events=2`。
- release check：**PASS**；仍为 7 张表、4 个页面、无延期表、生产产物存在。
- TypeScript check：**PASS**，无类型错误。
- Vite production build：**PASS**，29 modules transformed，耗时 359 ms。
- 构建产物：HTML 0.46 kB、CSS 10.26 kB、JS 97.25 kB。

pytest 和 acceptance 仍显示 Phase 1 已记录的两类 Starlette TestClient 依赖弃用提示；它们不是测试失败，本次没有借 Bugfix 扩大范围升级测试基础设施。

## 11. 边界复核与停止点

- 数据库仍严格为原 7 张表，没有 Schema 变更。
- API 路径数量和领域模块不变。
- 没有新增 LLM、Agent、RAG、Quality/AgentOps。
- 没有创建 ResumeVersion、CandidateSkill、AgentMemory、PendingAction。
- 没有实现官网抓取或自动投递。

Phase 1.1 已完成，当前停止，等待确认后再决定是否进入 Phase 2。
