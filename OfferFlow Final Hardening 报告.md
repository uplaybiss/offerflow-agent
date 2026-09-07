# OfferFlow Final Hardening 报告

## 1. 封版结论

OfferFlow 已完成本次限定范围内的 8 项 Final Hardening，版本标记更新为 `5.1.0-rc1`。业务架构仍保持 FastAPI + Vue 3 + SQLite + 单 Agent + Tool Calling + PendingAction + Trace/Eval + AgentOps，没有引入 RAG、多 Agent、爬虫、自动投递或新的通用工作流引擎。

可复现结果：`pytest` 73/73 通过，Phase 1～5 acceptance 全部通过，Final Hardening acceptance 11/11 通过，脚本化 Agent Contract/Safety Eval 8/8 通过，真实 Qwen synthetic smoke 通过。

## 2. 8 项 Hardening 实现结果

1. Matching Correctness：已合并偏好与已确认简历中的语言事实；加入确定性语言 canonicalization；CLOSED/EXPIRED 作为硬失败；删除 `critical_required_skills`/`critical_gaps` 死逻辑。
2. API Payload Schema：主要写接口、解析接口与控制接口改用 Pydantic 外层模型；错误 JSON shape 和字段类型稳定返回 4xx。
3. Skill Gap：改为按 `canonical_skill` 聚合，同义写法不再重复计数。
4. AgentMemory：Career Agent 页面恢复 chat 时读取 Memory，但通过 Jobs/Applications/Interviews/Tasks 正式 API 重新验证对象；不恢复聊天全文。
5. history_messages：Service 仅保留绝对安全上限 20，最终 1～20 窗口由 Runner 按发布配置执行；Trace 记录配置值和实际使用值。
6. Agent Contract/Safety Eval：保留原 8 条确定性业务回归，另增 8 条脚本化 Agent 工具契约与安全评测。
7. Tool Whitelist：不可变配置新增 `enabled_tools`，Runner 只注册白名单中的实际 Tool；stable/canary 可使用不同白名单。
8. Interview Progression：在原 10 Tool 目录内扩展 `propose_application_change` 的结构化 `action_type`，新增受控组合事务，不增加第 11 个 Tool。

## 3. 修改文件

核心后端：

- `matching/dictionary.py`、`matching/service.py`
- `career/models.py`、`career/repositories/pending_actions.py`
- `career/services/pending_actions.py`、`career/services/skill_gaps.py`
- `agent/runner.py`、`agent/service.py`、`agent/tools.py`
- `agentops/service.py`、`agentops/store.py`
- `api/schemas.py`、`api/main.py`
- `api/routers/agent.py`、`agentops.py`、`applications.py`、`auth.py`、`candidate.py`、`jobs.py`、`matching.py`、`parsing.py`、`tasks.py`
- `core/container.py`、`core/database.py`
- `quality/contract_eval.py`、`quality/contract_scenarios.py`、`quality/management.py`、`quality/store.py`、`quality/trace.py`
- `prompts/career_agent_v1.txt`

前端与发布：

- `frontend/src/views/CareerAgentView.vue`、`AgentOpsView.vue`、`JobCenterView.vue`
- `frontend/src/types.ts`、`frontend/src/styles.css`、`frontend/package.json`
- `tests/test_final_hardening.py`、`tests/test_phase5.py`
- `scripts/run_final_hardening_acceptance.py`、`scripts/release_check.py`
- `.github/workflows/ci.yml`、`README.md`

## 4. 数据库变化

业务表仍为 9 张，没有新增业务表。`pending_actions.action_type` 的 CHECK 约束由仅允许 `APPLICATION_TRANSITION` 扩展为允许 `APPLICATION_TRANSITION` 与 `INTERVIEW_PROGRESSION`。启动迁移会在一个事务中重建旧约束表、复制原数据、恢复索引；旧动作语义不变。

`quality.db` 的 `agent_runs` 增加 `enabled_tools_sha256`、`enabled_tool_count`、`history_messages`、`history_messages_used`，用于记录实际发布配置摘要，不记录完整消息或敏感正文。

`agentops.db` 没有新增表。配置 JSON 新增 `enabled_tools`；历史配置缺少该字段时迁移为“启用原有全部 10 个 Tool”，等价保持旧版本行为，并追加 `CONFIG_SCHEMA_MIGRATED` 审计事件。

## 5. Agent Tool 最终清单

只读工具：

1. `get_candidate_360`
2. `search_jobs`
3. `get_job_detail`
4. `analyze_job_match`
5. `compare_jobs`
6. `analyze_skill_gaps`
7. `query_applications`
8. `list_upcoming_tasks`

受控写工具：

9. `propose_application_change`
10. `confirm_application_change`

总数保持 10。所有 Tool 都不接受 `candidate_id`，账号和 Candidate 由服务端 `ContextVar` 请求上下文注入。

## 6. Tool Whitelist 机制

`enabled_tools: list[str]` 是不可变 AgentConfig 的正式字段。配置创建/校验会拒绝空数组、重复项和未知工具。Runner 用白名单过滤 `CAREER_TOOL_CATALOG` 后再构造 Agent schema；白名单不是仅用于展示。

stable 与 canary 可以发布不同白名单，例如 stable 暴露全部 10 个工具、canary 仅暴露前 8 个只读工具。Trace/Runtime Snapshot 保存 whitelist 的 SHA-256 摘要和 Tool 数量。即使白名单包含确认工具，后端缺少临时 confirmation grant 时仍返回 `CONFIRMATION_REQUIRED`。

## 7. PendingAction 最终协议

正式动作类型为：

- `APPLICATION_TRANSITION`：单一 Application 状态迁移。
- `INTERVIEW_PROGRESSION`：完成当前面试、创建下一轮和准备 Task 的组合动作。

提议阶段只持久化确认卡，包含 actor、candidate、chat、结构化 payload、request hash、版本快照和过期时间，不修改目标业务对象。确认阶段只能由前端结构化二次请求触发服务端临时 grant；模型自行调用确认工具没有授权能力。重复提议按请求哈希复用，重复确认返回既有结果。

## 8. Interview Progression 原子事务

确认时执行 `BEGIN IMMEDIATE`，依次校验 actor、Candidate ownership、PendingAction 状态与过期时间、请求哈希、Application 状态/版本、当前 Interview 归属/状态/版本，然后原子执行：

1. 当前 Interview 更新为 `COMPLETED` 并保存结果；
2. 创建下一轮 `SCHEDULED` InterviewRound；
3. Application 保持 `INTERVIEW`、更新 next action 并递增版本；
4. 创建与下一轮关联的 P1 Interview Task；
5. 写入 `INTERVIEW_PROGRESSED` ApplicationEvent；
6. PendingAction 更新为 `EXECUTED` 并保存结构化结果。

测试通过 SQLite trigger 在 Task 插入点强制失败，验证 Interview/Application/Event/PendingAction 全部回滚。重复确认不会重复创建 Interview、Task 或 Event；stale Application/Interview version 返回 409 语义冲突。

## 9. Matching 最终规则

`heuristic_v1` 只包含：Hard Conditions、required skills、preferred skills、required coverage、preferred coverage 与具体缺口。

语言事实为 `preferences.languages + current_resume_parsed.languages` 的确定性去重合并。显式别名包括 English/英语/英文、Chinese/中文/汉语/普通话、Japanese/日语、Korean/韩语；不使用 LLM 判断等价或推断熟练度。岗位有明确语言要求且 Candidate 缺失时为 FAIL；岗位无语言要求时为 UNKNOWN。

Job availability 规则为 ACTIVE 正常比较，EXPIRED/CLOSED 硬失败，ARCHIVED 作为用户管理状态而非能力失败。任何 Hard Condition FAIL 均为 `NOT_RECOMMENDED`。0.8/0.6 仍是可配置 heuristic 阈值，不声称有历史录用数据依据。

## 10. Skill Gap 聚合规则

所有计数来自当前 Candidate 正式保存的 Job 数据。聚合 key 为 `canonical_skill`，同时保留 display name、category、required/preferred count、涉及 Job 数、Candidate 是否已具备及原始 variants。

结果明确拆分为：`frequent_present`、`frequent_missing_required`、`frequent_missing_preferred`、`low_frequency_missing`。测试中 `FastAPI` 与 `Fast API` 只产生一个 `fastapi` 项，`required_count=2`、`total_jobs=2`。

## 11. AgentMemory 恢复机制

进入 Career Agent 页面时并行读取 Memory 和 Jobs/Applications/Interviews/Tasks 正式 API。Memory 仅提供 ID 引用；selector 只有在正式 API 返回相同且属于当前 Candidate 的对象时才恢复。ARCHIVED Job、安全删除后的空引用和跨账号对象不会成为当前上下文，也不会使页面整体失败。聊天原文不写入 Memory，也不从 Memory 恢复。

## 12. Agent Contract Eval Case 清单

`career-agent-contract-v1` 使用隔离临时数据库、synthetic data 与 Scripted Runner，但调用真实 LangChain Tool 对象并产生真实 Trace：

1. 收藏且未投岗位：只调用 `search_jobs`，不跨账号、不写入。
2. 只分析岗位：调用详情和 Matching，只读且业务库不变。
3. 自然语言修改状态：查询后只 propose，Application 保持原状态。
4. 模型自行 confirm：无服务端 grant，被 `CONFIRMATION_REQUIRED` 阻断。
5. 跨 Candidate 对象：安全 404/NotFound 语义，双方业务对象不变。
6. Prompt Injection：文本无法覆盖确认授权边界。
7. 未来三天事项：只调用 `list_upcoming_tasks`。
8. 多个 Job/Application：正确选择“百度”对应的 application/job，不误引用其他记录。

结果：8/8 通过，并持久化到通用 Eval Run/Case Result 表；结果只保存安全布尔值、数量和 Tool 名，不保存个人数据。

## 13. Deterministic Regression 与 Agent Eval 的区别

`career-agent-fixed-v1` 的 8 条用例验证 Matching、Application Service、PendingAction 和确认写入，是确定性业务回归，可做基线 hash 对比与 replay。

`career-agent-contract-v1` 的 8 条用例验证“脚本化模型决定调用什么 Tool”之后的路由、参数、隔离、禁止写入和 Trace 契约。它比单纯 Service 测试更接近 Agent orchestration，但仍不是外部模型效果评测。真实 Qwen 只保留一个不进入 CI 的 synthetic smoke。

## 14. 全量测试结果

- `python -m pytest -q`：73 passed，0 failed。
- 唯一提示为 Starlette TestClient 引用 AnyIO 兼容别名的依赖级 DeprecationWarning，不影响当前执行结果。

新增 Hardening 测试覆盖语言合并、CLOSED、canonical gap、错误 JSON shape、Memory 恢复与隔离、history 4/12/20、whitelist 配置/迁移/stable-canary/Trace、确认授权、组合事务成功/幂等/冲突/跨账号/沙箱/故障回滚、Contract Eval 和 Trace 隐私边界。

## 15. Phase 1～5 回归结果

- Phase 1 acceptance：PASS。
- Phase 2 acceptance：PASS。
- Phase 3 acceptance：PASS。
- Phase 4 acceptance：PASS，固定业务回归 8/8。
- Phase 5 acceptance：PASS，发布 generation 流程按 1 → 2 → 3 验证，stable/canary 与回滚均通过。

## 16. Final Hardening Acceptance

`scripts/run_final_hardening_acceptance.py` 的 11 个验收组全部通过，实际覆盖语言命中、CLOSED 拒绝、技能聚合、malformed payload、Memory、20 条历史、只读 whitelist、Contract Eval、面试 propose/confirm、重复 confirm 和 Trace 隐私/配置身份。

结果：`FINAL HARDENING ACCEPTANCE: PASS (11/11 acceptance groups)`。

## 17. TypeScript、Vite、compile 与 pip check

- `python -m pip check`：No broken requirements found。
- `python -m compileall -q ...`：PASS。
- `vue-tsc --noEmit`：PASS。
- Vite production build：PASS，33 modules transformed；生成 `dist/index.html`、CSS 与 JS 生产资产。

## 18. Live Qwen smoke 结果

非 CI 的 `scripts/run_phase5_live_agent_smoke.py` 使用临时 synthetic Candidate/Job 执行通过。实际模型为 `qwen3.8-27b`，调用 `search_jobs`，发布通道为 STABLE、generation=1。该单次 smoke 只证明当前 Key/模型/兼容接口可完成基础 Tool Calling，不代表长期稳定性或模型质量指标。

## 19. 当前真实边界

这是面向个人秋招流程的本地单用户/轻量多账号 Agent 工作台，不是企业级招聘平台、生产级分布式 Agent 平台或大规模自动求职系统。

已实现：求职业务管理、deterministic matching、Agent Tool Calling、confirmation write、Trace/Eval、AgentOps。

未实现：大规模官网抓取、自动登录/自动投递、自动邮件/联系 HR、多 Agent、RAG、分布式服务、生产级 IAM / Config Center / Observability、学习排序模型、ResumeVersion 与 CandidateSkill 独立表。

## 20. 未解决问题

- SQLite、本地进程和轻量 Session 适合个人/演示使用，不具备分布式高可用语义。
- “周五”等相对时间仍需要模型结合当前时间解析为明确 ISO 时间；有歧义时 Prompt 要求先澄清，后端只接受明确时间。
- live smoke 是一次基础链路检查，不替代长期在线可用性、成本、延迟或模型质量评测。
- 本地首次启动的 `demo/demo`、`admin/admin` 和默认 Session Secret 仅供开发，非本地使用必须更换。
- 当前测试有一个第三方 TestClient/AnyIO DeprecationWarning，尚未影响功能或测试通过。

## 21. README 更新内容与 Git 状态

README 已更新为 Release Candidate，并使用要求中的准确定位：“面向个人秋招流程的本地单用户/轻量多账号 Agent 工作台”。文档明确区分已实现和未实现能力，补充语言匹配、canonical skill gap、Memory 恢复、Tool Whitelist、Interview Progression、两类 Eval、Final Hardening 验收和 live smoke 边界。

Git 仓库已经初始化且忽略 `.env`、`runtime/*.db`、`.venv`、`node_modules`、`frontend/dist`、`__pycache__` 和测试临时数据库；秘密扫描未发现 Key 或 Session Secret 被跟踪。作者身份仅配置在当前仓库。提交历史保持真实，没有伪造 Phase 1～5 的分阶段提交：

1. `fb31b9a Baseline before final hardening`：记录 Hardening 前的 Phase 1～5 最终现状。
2. `Final hardening and release candidate`：记录本报告所述的全部封版改动，由本报告所在提交承载。

第二个提交完成后预期工作树为空；由于 Git commit hash 包含本报告自身内容，报告不写入自引用且会随 amend 改变的第二个 hash，以提交日志为最终事实源。

完成以上封版后停止继续增加功能，等待统一代码验收和真实使用反馈。
