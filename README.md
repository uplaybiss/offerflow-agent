# 第一次使用 OfferFlow

OfferFlow 是一款 **AI 求职投递与简历优化工作台**。它围绕你自己找到的真实 JD，帮助你判断岗位匹配度、基于已有事实优化简历，并持续管理投递、笔试、面试、待办和后续对话。

## 第一步：个人中心

填写应届生届别、目标岗位、期望城市、真实掌握的技能和求职偏好，并上传或粘贴一份基础简历。基础简历代表“我是谁”，后续匹配和优化都以这里确认过的事实为准。

## 第二步：岗位中心

在招聘官网、Boss、牛客等网站看到岗位后，复制 JD，在“新增岗位”中粘贴并点击 AI 解析。检查公司、岗位、地点、要求等字段，确认无误后保存。OfferFlow 只管理你主动保存的岗位，不会自动搜索互联网。

## 第三步：岗位匹配

打开已保存岗位，查看硬条件、已匹配技能、必需技能覆盖、加分技能覆盖和明确缺口。匹配由可复现的 `deterministic matching` 规则计算，等级只是辅助筛选的启发式结果，不是录用概率。

## 第四步：简历中心

选择“基础简历 + 目标岗位”，点击“针对岗位优化”。系统会展示岗位核心要求、明确匹配、已有但不够突出的事实、真实缺口和逐条修改建议。人工检查并编辑后，点击“保存为新版本”，生成关联该岗位的 ResumeVersion；基础简历不会被覆盖。

## 第五步：投递进度

真实投递后建立记录，并按实际进展更新：准备投递 → 已投递 → 笔试 / 测评 → 面试 → Offer / 已淘汰。页面的“下一阶段”直接读取后端状态机，不需要手填内部状态。

## 第六步：今日工作台

查看全部待办、近期面试、逾期待办和投递漏斗。岗位截止、测评或面试产生的建议只有在你确认后才会成为正式待办。

## 第七步：求职 Agent

可以直接问：

- “阿里这个 JD 和我的简历差在哪？”
- “我这周有什么面试？”
- “帮我记一下周五准备阿里一面。”

Agent 会优先从自然语言和当前对话识别已保存的业务对象。创建待办或改变投递状态时，它只能先生成确认卡；你点击确认后才会写入。聊天记录会持久化，第二天仍可打开原对话继续处理同一岗位。

## 本地启动

需要 Python 3.11+、Node.js 20+ 和 PowerShell 7。在项目目录执行：

```powershell
cd D:\offerflow-agent
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
corepack pnpm --dir frontend install
Copy-Item .env.example .env
```

如需使用真实 AI 解析和 Agent，在 `.env` 中填写自己的 DashScope Key；不要把 `.env` 提交到 Git：

```text
DASHSCOPE_API_KEY=你的_Key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CHAT_MODEL_NAME=qwen3.8-27b
```

启动应用：

```powershell
.\.venv\Scripts\python.exe app.py
```

浏览器打开 `http://127.0.0.1:8000`。本地开发默认账号为 `demo/demo`，管理员账号为 `admin/admin`；离开本机开发环境前必须更换默认密码和 `SESSION_SECRET`。

没有模型 Key 时，个人中心、岗位中心、简历版本、投递、面试、待办、确定性 Matching 和 AgentOps 离线评测仍可使用；AI 解析、简历建议和真实 Agent 对话需要有效的兼容接口配置。

## 产品边界

OfferFlow 负责：

- JD 导入、AI 解析、人工校对与岗位管理
- 岗位匹配、硬条件检查和技能缺口说明
- 基于真实候选人事实的简历优化与 ResumeVersion 快照
- 投递状态、Application Event、面试轮次和待办管理
- 单求职 Agent、受控写入和持久化聊天记录
- Trace、Eval 和管理员 AgentOps

OfferFlow 不负责：

- 自动发现或实时联网搜索岗位
- 招聘网站爬虫、浏览器自动化或定时同步
- 自动填写网申、自动投递或联系 HR
- 多 Agent、RAG 或通用工作流引擎
- 企业级招聘 ATS、微服务或分布式服务

当用户要求查找网上最新岗位时，Agent 会说明当前无法联网找岗位，并引导用户把真实 JD 粘贴到岗位中心。`search_jobs` 只查询用户已经保存到本地 SQLite 的岗位。

## 简历事实安全

JD 只能作为岗位要求，不能变成候选人事实。模型可以重排和改写已有内容、突出相关项目、指出缺口或建议用户补充真实材料，但不得凭空增加技术、经历、职责、奖项、规模、性能或测试指标。

每条简历建议包含修改位置、修改类型、原文、建议文本、理由、事实依据和对应 JD 要求。服务端会检查新出现的已知技能和显式数字：无事实依据时标记 `UNSUPPORTED`，无法自动判断的自由文本标记 `NEEDS_USER_REVIEW`。这是一道可验证的安全护栏，不代表系统已经完全解决自然语言事实核验。

所有 AI 结果先作为 Preview。只有用户人工编辑并明确点击“保存为新版本”后才创建 ResumeVersion；版本记录创建时的基础简历哈希和内容快照，之后基础简历变化不会偷偷改写旧版本。

## 数据与执行模型

业务库使用 SQLite WAL，共 12 张业务表：

- 身份与业务：`users`、`candidate_profiles`、`jobs`、`applications`、`application_events`、`interview_rounds`、`job_search_tasks`
- Agent 控制：`agent_memories`、`pending_actions`
- v5.2 工作区：`resume_versions`、`chat_threads`、`chat_messages`

三个概念彼此独立：

- Chat History 记录“我们聊过什么”，保存用户和 Assistant 正文。
- AgentMemory 记录“当前对话关联什么”，只保存对象 ID 和受控目标标签。
- Trace 记录“系统执行了什么”，只保存工具、状态、耗时、对象 ID、配置版本、Token 等安全元数据，不保存完整聊天、简历正文、完整 JD 或 CoT。

业务时间统一存 UTC；展示时区由 `APP_TIMEZONE` 配置，默认 `Asia/Shanghai`。

## Agent Tool Calling 与受控写入

当前单 Agent 工具清单：

读取和分析：

1. `get_candidate_360`
2. `search_jobs`
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

Agent 工具不接收客户端提供的 `candidate_id`；当前用户和 Candidate 上下文由服务端注入。`confirmation write` 遵循“提议 → PendingAction 确认卡 → 用户确认 → 服务端校验 → 原子写入”。PendingAction 绑定 actor、请求哈希、过期时间、关联对象和 version CAS；重复确认保持幂等，取消或未确认不会改变业务表。

## AgentOps

AgentOps 只对管理员显示，用于管理模型、Prompt、Tool whitelist、stable/canary 发布、Trace 和 Eval：

1. 创建不可变配置草稿并验证。
2. 发布到 stable，或按比例发布到 canary。
3. 发布使用 `generation` CAS 和幂等 `command_id`，防止旧页面覆盖新配置。
4. Tool whitelist 决定该配置实际暴露给模型的 Tool schema。
5. 查看 Run、错误率、P50/P95、Token、Trace、固定评测和基线对比。
6. 需要时回滚运行配置；回滚不会倒退业务数据库。

固定业务回归、Agent Contract/Safety Eval 和 Resume Tailoring Eval 使用隔离的 synthetic data，不应解释为真实模型效果或录用表现。

## 常用配置

```text
OFFERFLOW_DB_PATH=runtime/offerflow.db
OFFERFLOW_QUALITY_DB_PATH=runtime/quality.db
OFFERFLOW_AGENTOPS_DB_PATH=runtime/agentops.db
APP_TIMEZONE=Asia/Shanghai
AGENT_MODEL_MAX_RETRIES=2
AGENT_HISTORY_MESSAGES=12
PENDING_ACTION_TTL_SECONDS=900
```

## 完整验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\run_phase1_acceptance.py
.\.venv\Scripts\python.exe scripts\run_phase2_acceptance.py
.\.venv\Scripts\python.exe scripts\run_phase3_acceptance.py
.\.venv\Scripts\python.exe scripts\run_phase4_acceptance.py
.\.venv\Scripts\python.exe scripts\run_phase5_acceptance.py
.\.venv\Scripts\python.exe scripts\run_final_hardening_acceptance.py
.\.venv\Scripts\python.exe scripts\run_v52_real_usage_acceptance.py
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q agent agentops api career core matching parsing quality scripts tests
corepack pnpm --dir frontend exec vue-tsc --noEmit
corepack pnpm --dir frontend build
.\.venv\Scripts\python.exe scripts\release_check.py
```

可选的真实模型冒烟：

```powershell
.\.venv\Scripts\python.exe scripts\run_phase5_live_agent_smoke.py
```

真实模型冒烟只使用临时 synthetic data，不读取或修改正式业务库，也不作为离线回归的通过条件。
