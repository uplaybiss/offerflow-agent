# OfferFlow v5.2 Real Usage Iteration 报告

## 1. 新产品定位

本轮将 OfferFlow 正式定位为：

> OfferFlow｜AI 求职投递与简历优化工作台

产品围绕用户自己找到的真实 JD，完成“导入 JD → 解析和校对 → 岗位匹配 → 基于事实优化简历 → 保存岗位定制版本 → 建立投递 → 跟踪笔试/面试/待办 → 在历史对话中继续处理”的闭环。

普通用户最终拥有 6 个页面：今日工作台、岗位中心、简历中心、投递进度、个人中心、求职 Agent。AgentOps 仍为管理员/开发者页面。

## 2. 为什么删除自动岗位搜索

真实使用的首要问题不是“再造一个不稳定的招聘爬虫”，而是把用户已经找到的 JD 转化为可比较、可定制简历、可持续跟踪的业务对象。招聘站点登录、反爬、页面变化、时效与真实性验证会显著扩大范围，也无法保证岗位真实有效，因此本轮彻底删除了在线发现目标。

已删除：

- `Live Job Search`、`search_live_jobs` 计划与来源刷新 API；
- `sources/adapters.py`、`career/services/sources.py`、`api/routers/sources.py` 及其装配代码；
- Company Source Registry、官网 Adapter、抓取、浏览器自动化、定时同步、自动登录和自动投递的产品入口。

`search_jobs` 继续保留，但语义严格限定为查询当前 Candidate 已保存到 SQLite 的岗位。Prompt 明确要求：用户询问网上最新岗位时，不得伪造实时搜索结果，应引导其把 JD 粘贴到岗位中心。

岗位的 `source_name`、`source_url` 等字段继续作为“用户记录这条 JD 来自哪里”的普通元数据存在，不代表存在抓取或刷新能力。

## 3. 用户反馈逐条修复

| 用户反馈 | 本轮结果 | 关键实现 |
|---|---|---|
| 普通页面像开发后台 | 删除 Phase、Prompt/Toolset/Trace policy、模型名等内部标签 | 6 个用户 View、Sidebar、Login |
| 业务枚举显示英文 | 建立统一中文映射，值仍按英文存储 | `frontend/src/uiLabels.ts`、`StatusBadge.vue` |
| 待办标题输入框被压窄 | 为标题、辅助字段、按钮设置明确 flex 规则 | `frontend/src/styles.css` |
| 岗位搜索框被压窄 | 为搜索字段和筛选字段设置独立伸缩宽度 | `frontend/src/styles.css` |
| 岗位中心不应“发现岗位” | 改为手工新增、粘贴 JD、解析、校对、收藏、筛选、匹配和比较 | `JobCenterView.vue` |
| 投递表单难理解 | 改为岗位选择 + 当前进度，只允许准备投递/已投递初始化 | `ApplicationTrackerView.vue` |
| 用户需要填写 `next_action` | 删除自由文本，下一阶段直接读取后端迁移图 | `/api/applications/transitions/config` |
| Candidate360 工程感过强 | 更名个人中心，保留真正需要的个人信息、技能和偏好 | `Candidate360View.vue` |
| 毕业年份表达不自然 | 改为动态“应届生届别”选择，底层字段继续兼容 | `Candidate360View.vue` |
| 用户被要求填写 JSON | 改为求职类型、语言、重点公司等正常表单 | `Candidate360View.vue` |
| AI 简历解析默认显示 JSON | 默认展示人类可读卡片，原始结构收进高级折叠 | `Candidate360View.vue` |
| 缺少岗位定制简历 | 新增简历中心、事实校验和 ResumeVersion | Resume Repository/Service/API/View |
| 刷新后聊天丢失 | 新增 Thread/Message 持久化和历史对话栏 | Chat Repository/Service/API/View |
| Context Selector 影响普通使用 | 默认折叠为“指定上下文（可选）” | `CareerAgentView.vue` |
| Agent 不能记录待办 | 新增 `propose_task_change` 与 `TASK_CREATE` 确认链路 | Agent Tool、PendingAction |
| Agent 可能假装联网找岗位 | Prompt 与测试明确禁止；在线来源代码彻底删除 | `career_agent_v1.txt`、`test_v52.py` |

本轮实现提交共变更 54 个文件（2,548 行新增、715 行删除）。新增核心文件包括聊天和简历的 Repository/Service/API、`ResumeCenterView.vue`、`uiLabels.ts`、v5.2 测试和 32 步验收脚本。

## 4. UI 前后对比

| 区域 | 迭代前 | v5.2 |
|---|---|---|
| 导航 | 候选人 360、投递追踪，缺少简历工作区 | 个人中心、投递进度、新增简历中心 |
| 页面文案 | Phase 标签、模型和内部版本信息 | 面向求职任务的中文说明 |
| 岗位中心 | 混有来源 Adapter/刷新概念 | 只管理用户保存的真实 JD |
| 岗位空状态 | 偏工程或“发现岗位”表达 | 明确提示粘贴来自招聘网站的 JD，并提供“新增岗位” |
| 个人资料 | JSON textarea、排除公司、canonical 术语 | 普通表单、标签编辑和人类可读预览 |
| 投递创建 | 英文状态、自由填写下一步 | 中文进度、后端状态机驱动下一阶段 |
| Agent | 技术状态和 Trace 占据普通页面 | 最近对话、聊天正文、可选上下文、确认卡 |
| 简历 | 只有 Candidate 当前简历 | 基础简历 + 岗位分析 + 独立版本库 |

AgentOps 保留模型、Prompt、Tool whitelist、Trace、Eval 和 stable/canary 等工程信息，普通用户页面不再展示。

## 5. 中文 Enum Mapping

数据库、Python Enum 和 API 合约继续使用稳定英文值，普通页面统一经 `uiLabels.ts` 显示中文：

- Application：`PLANNED` 准备投递、`APPLIED` 已投递、`ASSESSMENT` 笔试 / 测评、`INTERVIEW` 面试、`OFFER` Offer、`REJECTED` 已淘汰、`WITHDRAWN` 已放弃。
- Job：`ACTIVE` 招聘中、`EXPIRED` 已截止、`CLOSED` 已关闭、`ARCHIVED` 已归档。
- Task Type：`GENERAL` 普通待办、`APPLICATION` 投递、`ASSESSMENT` 笔试 / 测评、`INTERVIEW` 面试、`MATERIAL` 材料准备、`FOLLOW_UP` 跟进。
- Task Priority：`P1` 紧急、`P2` 普通、`P3` 低。
- Task Status：`TODO` 待处理、`IN_PROGRESS` 进行中、`DONE`/`COMPLETED` 已完成、`CANCELLED` 已取消。
- Interview、匹配等级、验证状态和 PendingAction 类型也由同一文件统一映射。

`StatusBadge` 的颜色仍按原始英文值决定，展示文本统一调用 `labelFor`，避免前端各页自行维护不同翻译。

## 6. CSS Bug 修复

今日工作台将 `.task-title-field` 设置为 `flex: 1 1 480px; min-width: 320px`，优先占据可用空间；优先级和截止时间固定合理宽度，添加按钮不被拉伸。

岗位中心将 `.search-field` 设置为 `flex: 1 1 560px; min-width: 360px`，状态选择固定 160px，收藏和操作按钮保持内容宽度。两个输入框不再被同一套通用 flex 规则压缩成窄白框。

同时新增简历分析卡片、版本列表、历史对话三栏、确认卡和响应式断点；小于 1380px 时 Agent 确认区换到下一行，简历摘要改为两列。

## 7. 个人中心最终结构

个人中心副标题为“管理你的个人信息、技能和求职偏好，用于岗位匹配和简历优化。”页面包括：

- 姓名、邮箱、手机、学历；
- 动态生成附近年份的应届生届别，下层继续保存 `graduation_year`；
- 目标岗位、期望城市、可在面试中真实解释和使用的技能；
- 求职类型、语言、重点公司等正常控件；
- 基础简历上传/文本编辑、AI 结构化 Preview 和确认保存；
- 教育、技能、语言、项目等人类可读卡片；原始结构仅在折叠详情中显示。

`excluded_companies` 仅作为后端兼容字段保留为空，不再出现在普通页面。页面不存在 JSON textarea、canonical skill 或 skill category 文案。

## 8. 简历中心设计

简历中心将“候选人事实”和“岗位使用版本”分开：

- 顶部直接读取 Candidate 当前简历作为基础简历，不复制第二份基础数据；
- 可查看文件名、更新时间、技能摘要并编辑基础文本；
- 从已保存 Job 中选择目标，生成结构化岗位定制分析；
- 分别显示岗位核心要求、明确匹配、已有但不够突出、真实缺口；
- 每条建议显示原文、建议、理由、事实证据、对应 JD 要求和服务端验证状态；
- 安全建议可应用到草稿，`UNSUPPORTED` 建议不可应用；
- 只有用户点击“保存为新版本”才落库；
- 版本支持查看、编辑、复制文本和归档，不实现 Word/PDF 导出。

新增 API：

- `POST /api/resume-tailoring/analyze`
- `GET|POST /api/resume-versions`
- `GET|PATCH /api/resume-versions/{resume_version_id}`
- `POST /api/resume-versions/{resume_version_id}/copy`

## 9. ResumeVersion Schema

`resume_versions` 是本轮唯一的简历派生表：

| 字段 | 语义 |
|---|---|
| `resume_version_id` | 版本主键 |
| `candidate_id` | 所属 Candidate，删除 Candidate 时级联 |
| `source_job_id` | 可选关联岗位，岗位删除后置空 |
| `title` | 用户可读版本名 |
| `base_resume_hash` | 创建时基础简历内容指纹 |
| `content_text` | 该版本独立文本快照 |
| `structured_json` | 小型结构化元数据，不拆 section/bullet 表 |
| `created_from` | `AI_TAILORED` 或 `MANUAL` |
| `archived` | 轻量归档标记 |
| `version` | 编辑时使用的乐观锁版本 |
| `created_at` / `updated_at` | UTC 时间 |

创建时强制使用当前 Candidate 的基础简历 hash，而不是信任客户端；更新时保留原始 `base_resume_hash` 和 `created_from`，使用 version CAS 防止旧页面覆盖新内容。旧版本内容不会随基础简历更新而改变。

业务库由 9 张增至 12 张，新增且仅新增 `resume_versions`、`chat_threads`、`chat_messages`，没有创建 resume sections、bullets、evidence、workflow 或 release 表。

## 10. JD → Resume Tailoring 链路

链路如下：

1. 服务端按 Candidate 身份读取 Job 与基础简历/指定 ResumeVersion；
2. Matching 服务先确定性整理硬条件、必备/加分技能命中和缺口；
3. 将 Candidate 已确认事实、简历文本、Job 要求和确定性结果交给 LLM；
4. JD 被明确标记为不可信输入，只能表达岗位要求；
5. LLM 只能返回结构化的 `underemphasized_facts` 与逐条 `suggestions`；
6. 服务端重新验证技能和数字，过滤无法在事实文本中找到的“不够突出事实”；
7. API 返回 Preview、验证状态和免责声明，不写 Candidate 或 ResumeVersion；
8. 用户编辑草稿并显式保存新版本。

同一能力也通过只读 Tool `analyze_resume_for_job` 提供给求职 Agent。

## 11. 简历事实安全边界

允许的事实来源只有基础简历、Candidate Profile、用户确认技能/教育/项目事实、已保存的 ResumeVersion。Job JD 仅可作为“目标岗位要求”。

允许模型做重写、排序、精简、突出已有经历和指出缺口；禁止凭空增加技能、项目、实习、职责、奖项、用户规模、性能指标、测试数量或上线结果。

AI 返回永远是 Preview，不自动覆盖基础简历，也不自动创建版本。v5.2 未给 Agent 增加“保存简历版本”的写 Tool，正式保存只在简历中心由用户发起。

## 12. Hallucination 防护

防护不是只依赖 Prompt：

- Prompt 明确把 JD 当作 untrusted input，JD 中的“忽略规则”等内容无权改变事实边界；
- 服务端使用 SkillDictionary 检查建议文本出现的已知技能是否属于 Candidate 已确认 canonical skill；
- 服务端提取建议文本中的显式数字，与基础简历和确认事实中的数字集合比较；
- 无依据技能或新数字标记 `UNSUPPORTED`，`safe_to_apply=false`；
- 无法自动判断的其他自然语言改写标记 `NEEDS_USER_REVIEW`；
- 原文未变化或空建议可标记 `SUPPORTED`；
- API 明示当前自动校验只覆盖技能与明确数字，不宣称完全解决自然语言事实验证。

## 13. Resume Tailoring Eval

`quality/resume_tailoring_cases.py` 固定登记 6 个场景，并在 `tests/test_v52.py` 中用隔离数据执行：

1. JD 要 Python、Candidate 有 Python：确定为 matched；
2. JD 要 Docker、Candidate 没有：保留 gap，建议不得把 Docker 写成已掌握；
3. 简历已有 Agent Tool Calling、JD 强调 Agent：允许建议突出已有事实；
4. JD 要 Kubernetes 和 3 年经验、Candidate 没有：相关技能和年限不得写入；
5. JD 含 Prompt Injection：不能覆盖事实规则；
6. 模型伪造“性能提升 80%”：服务端标记 `UNSUPPORTED`。

这些是确定性安全回归，不代表真实模型整体质量统计。

## 14. Chat History

新增 `chat_threads` 与 `chat_messages`：

- Thread 记录 Candidate、标题、归档状态和更新时间；
- Message 只允许 `USER` / `ASSISTANT`，限制正文长度，不保存 CoT、Key、Cookie 或 Tool 敏感结果；
- 第一条用户消息压缩空白并截断至 36 字生成标题，不额外调用 LLM；
- 最近对话按更新时间倒序，支持新建、打开、重命名、删除；
- 删除 Thread 通过外键级联删除 Message，同时删除对应 AgentMemory；
- Agent 运行前从数据库读取最近 N 条，客户端传入的旧 history 不作为权威来源；
- 用户消息和 Assistant 最终回答分别持久化，服务重启后可恢复。

新增 API：`GET|POST /api/chat-threads`、`GET|PATCH|DELETE /api/chat-threads/{chat_id}`。所有读取和变更都带 Candidate 条件。

## 15. Chat History / Memory / Trace 区别

| 数据 | 回答的问题 | 保存内容 | 明确不保存 |
|---|---|---|---|
| Chat History | 我们聊过什么 | 用户和 Assistant 正文 | CoT、Key、Cookie、未过滤 Tool 敏感结果 |
| AgentMemory | 当前对话关联什么 | Job/Application/Interview/Task ID、受控 `last_goal` | 消息正文、简历、JD |
| Trace | 系统执行了什么 | Tool、risk、status、latency、对象 ID、配置版本、Token、安全指标 | 完整聊天、完整简历、完整 JD、CoT |

恢复历史会先加载 Message 和 Memory，再按当前 Candidate 从正式 Repository/API 重新查询业务对象。已删除、归档、跨 Candidate 或业务链不一致的引用会被清空或拒绝，不把 Memory 当作业务事实副本。

## 16. Task Agent 写入

新增 `propose_task_change`，参数包括标题、Task Type、明确 ISO 截止时间、优先级、说明及可选 Job/Application/Interview 关联。

Agent 可把“明天”“周五”等相对时间理解为用户意图，但传入 Service 前必须变成明确 ISO 时间；确认卡展示实际截止时间，不无声隐藏默认时刻。若用户说“只告诉我怎么准备，不要创建待办”，Prompt 与工具路由测试要求不得调用写 Tool。

确认前只返回 `TASK_CREATE` PendingAction，Task 表不变；用户确认后才创建 `TODO` Task。确认响应返回 `task_id`，页面随后刷新待办。

## 17. PendingAction

`PendingActionType` 和数据库 CHECK 增加 `TASK_CREATE`，旧数据库启动时会安全迁移该约束。其安全契约保持不变：

- actor 与 Candidate 由服务端会话确定；
- 请求内容计算稳定 hash，重复提议复用同一待确认动作；
- PendingAction 有有效期，取消不写业务数据；
- 确认时再次验证 Job/Application/Interview 均属于当前 Candidate；
- 同时给出多个关联时，校验它们属于同一业务链；
- Task 创建与 PendingAction 执行状态在同一个 SQLite 事务完成；
- 重复确认读取既有结果，不重复创建 Task。

Application Transition 和 Interview Progression 的原子事务、Event、CAS 和幂等行为均保留。

## 18. Agent Tool 最终清单

最终 Toolset 为 `career-tools-v2`，共 12 个：

读取/分析：

1. `get_candidate_360`
2. `search_jobs`（仅本地已保存岗位）
3. `get_job_detail`
4. `analyze_job_match`
5. `compare_jobs`
6. `analyze_skill_gaps`
7. `query_applications`
8. `list_upcoming_tasks`
9. `analyze_resume_for_job`

受控写入：

10. `propose_application_change`
11. `propose_task_change`
12. `confirm_application_change`

AgentOps 的默认配置、旧完整目录迁移、Tool whitelist、Runtime Snapshot 和 Trace 已同步到 12 个工具；自定义的部分 whitelist 不会在迁移时被擅自扩展。

## 19. 全量测试

本轮最终验证结果：

| 检查 | 结果 |
|---|---|
| `python -m pytest -q` | 83 passed，1 条 Starlette TestClient 依赖弃用 warning |
| Phase 1 acceptance | PASS，6 组 |
| Phase 2 acceptance | PASS，6 组 |
| Phase 3 acceptance | PASS，8 组 |
| Phase 4 acceptance | PASS，8 组；固定评测 8/8、回放 MATCH |
| Phase 5 acceptance | PASS，9 组；stable/canary generation 1→2→3 |
| Final Hardening acceptance | PASS，11/11 组 |
| v5.2 Real Usage acceptance | PASS，32/32 步 |
| `pip check` | No broken requirements found |
| `compileall` | PASS |
| `vue-tsc --noEmit` | PASS |
| Vite production build | PASS，36 modules transformed |
| `release_check.py` | PASS：12 business / 5 quality / 4 AgentOps tables，12 tools |
| `git diff --check` | PASS；仅提示 Git 将 LF 按仓库配置转换为 CRLF |
| 凭据检查 | `.env` 未跟踪且被 `.gitignore` 忽略，代码差异未发现 Key 形态 |

旧测试/验收中要求 Phase 标签、英文枚举、JSON textarea、9 张业务表、10 个工具或来源刷新接口的断言已更新。原因是这些断言验证的是被本轮明确替换的旧产品交互，而不是业务安全契约；状态机、Event、CAS、幂等、Candidate 隔离、语言/技能归一化、Hard Reject、AgentMemory、Tool whitelist、PendingAction、Interview Progression、Trace allowlist 和 AgentOps 发布控制仍持续回归。

## 20. v5.2 acceptance

`scripts/run_v52_real_usage_acceptance.py` 使用临时 SQLite 与 synthetic AI 响应实际走通以下 32 步，结果全部 PASS：

1. 登录；2. 打开个人中心；3. 普通页无 Phase/JSON/工程术语；4. 设置届别/城市/岗位/英语/重点公司；
5. 保存基础简历；6. 粘贴 synthetic AI 应用 JD；7. AI 解析 Preview；8. 人工确认保存 Job；
9. Matching 命中 Python/Agent 且识别 Docker 缺口；10. 进入简历中心；11. 选择 Job；12. 生成优化 Preview；
13. 可突出已有 Agent/Tool Calling；14. 不把 Docker 写成已掌握；15. 保存“阿里 AI应用版”；16. 基础简历不变；
17. 建立投递；18. 页面使用中文状态；19. 更新为已投递；20. Agent 返回真实简历差异；
21. Agent 接收周五待办请求；22. 产生 Task PendingAction；23. 未确认无 Task；24. 用户确认；25. Task 创建；
26. 新建聊天；27. 刷新后重新加载；28. 历史正文存在；29. AgentMemory 恢复 Job ID；
30. 业务事实重新查询正式 API；31. Trace 不含聊天、基础简历和完整 JD；32. AgentOps 正常工作。

该脚本不读取或修改正式运行库。

## 21. README 用户指南

README 已从工程能力列表改为用户任务优先，并以 `# 第一次使用 OfferFlow` 开头。顶部依次说明个人中心、岗位中心、岗位匹配、简历中心、投递进度、今日工作台和求职 Agent 七步真实使用流程；之后才介绍启动配置、产品边界、事实安全、数据模型、Tool Calling、CAS、Trace、Eval 和 AgentOps。

README 同时明确：无 Key 时哪些本地业务仍可使用；`.env` 不应提交；`search_jobs` 只查 SQLite；项目负责和不负责的边界；完整离线验证命令。

## 22. 当前限制

- OfferFlow 不自动发现互联网岗位，不含招聘爬虫、自动登录、自动网申、自动投递或 HR 联系。
- v5.2 不实现 Word/PDF 自动排版导出，只提供版本文本查看、编辑和复制。
- 简历事实验证只自动覆盖 SkillDictionary 中的技能和显式数字；其他自由文本仍需人工核对。
- AI 解析、简历建议和真实 Agent 对话依赖用户配置的 DashScope 兼容接口；离线测试使用 synthetic fake，不代表线上模型稳定性。
- 当前是本地 SQLite WAL、单 Agent 和轻量账号模型，不是企业 ATS、生产级 IAM、微服务或分布式系统。
- 未增加 RAG、多 Agent、CandidateSkill 拆表、Resume Workflow、自动海投、邮件或通用 Workflow Engine。
- Starlette TestClient 产生 1 条上游依赖弃用 warning，不影响本轮测试通过。

完成后应进入真实使用：导入真实 JD、保存真实岗位版本、记录真实投递并收集反馈；本轮不继续扩展新模块。

## 23. Git commit

实现代码、测试、README 和验收脚本已提交：

- Commit：`53018d9`
- Message：`feat: deliver OfferFlow v5.2 resume workspace`
- Author：`Jing Wang <a2272194724@gmail.com>`
- Branch：`main`
- 基线：`070a432 Final hardening and release candidate`

本报告在实现提交完成并取得可验证哈希后生成，将作为独立文档提交保存。
