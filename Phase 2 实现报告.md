# OfferFlow Phase 2 实现报告

## 1. 验收结论

Phase 2“结构化解析与 heuristic_v1 Matching”已按确认边界完成，Phase 1 业务闭环保持可用。

- 数据库仍严格为 7 张业务表，没有新增 `ResumeVersion`、`CandidateSkill`、`AgentMemory` 或 `PendingAction`。
- 简历 TXT/PDF 提取、简历结构化预览、JD 结构化预览已实现。
- 所有解析结果默认只存在于当前浏览器编辑态；只有用户点击确认保存，才调用原有 Candidate/Job API 写入正式数据。
- Matching 的硬条件、技能覆盖、缺口和等级均由确定性代码计算；模型只负责解析或解释，不参与匹配事实和等级决策。
- canonical skill 与 skill category 已分离；同属 `backend_framework` 不会导致 `FastAPI` 命中 `Django`。
- 前端仍为 4 个主页面，没有提前增加 Career Agent 页面。
- 自动化测试 26 项全部通过，Phase 1/Phase 2 验收、TypeScript 检查、Vite 生产构建和发布检查均通过。
- 真实 DashScope 请求已实际发出，但当前可发现的密钥返回 HTTP 401；因此真实 Qwen 冒烟如实记为“鉴权待更新”，不计为通过。

Phase 2 完成后停止，未进入 Phase 3。

## 2. 业务链路

### 2.1 当前简历

1. 用户选择 TXT/PDF。
2. 后端只提取文本与文件元信息，不写数据库。
3. 未配置模型时，用户可直接编辑文本和结构化 JSON。
4. 配置模型时，可生成结构化预览；未知字段保持空值，不允许用宽泛技能分类替代具体技能。
5. 用户校对并点击“确认保存档案”后，才通过 Candidate `version` CAS 覆盖当前简历。

第一版只维护当前简历，不产生简历版本历史。

### 2.2 JD

1. 用户粘贴原始 JD。
2. 模型解析只填充可编辑表单，不创建 Job。
3. 用户校对公司、岗位、地点、招聘批次、毕业年份、截止日期、必需/加分技能和硬条件。
4. 用户明确提交后，才创建 Job；解析元数据复用现有 `source_metadata` JSON 保存。

未配置模型时，原有手工录入流程完整保留。

### 2.3 Matching

1. 读取正式 Candidate 与正式 Job。
2. 判断岗位截止日期、毕业年份、排除公司、地点/远程、用工类型、学历、语言、签证等硬条件。
3. 使用 `skill_dictionary_v1` 将候选人与岗位技能分别归一化为 canonical skill，并保留 skill category 作为展示维度。
4. 仅 canonical skill 相同才算命中；category 相同不产生命中。
5. 计算 required/preferred skill coverage，输出逐项命中证据与具体缺口。
6. 使用可配置 `heuristic_v1` 生成工程分级，并计算确定性 SHA-256 结果指纹。
7. 可选模型解释只接收上述确定性事实，不能改写等级、命中和缺口。

## 3. 数据库

Phase 2 没有数据库迁移，继续使用以下 7 张表：

1. `users`
2. `candidate_profiles`
3. `jobs`
4. `applications`
5. `application_events`
6. `interview_rounds`
7. `job_search_tasks`

Phase 2 数据复用现有字段：

- 当前简历文本：`candidate_profiles.current_resume_text`
- 当前简历结构：`candidate_profiles.current_resume_parsed_json`
- 当前简历文件名与摘要：`current_resume_filename`、`current_resume_sha256`
- 候选人技能：`candidate_profiles.skills_json`
- 岗位技能：`jobs.required_skills_json`、`jobs.preferred_skills_json`
- JD 解析硬条件与解析器指纹：`jobs.source_metadata_json.phase2_parsed`

SQLite 继续启用 WAL；业务时间继续存 UTC，展示时区默认 `Asia/Shanghai` 且可通过 `APP_TIMEZONE` 配置。

## 4. 新增 API

| 方法 | 路径 | 作用 | 是否直接持久化 |
|---|---|---|---|
| GET | `/api/parsing/capabilities` | 返回文件限制、模型可用性、provider/model | 否 |
| POST | `/api/parsing/resume/extract` | 提取 TXT/PDF 文本、SHA-256、字符数 | 否 |
| POST | `/api/parsing/resume/preview` | 生成当前简历结构化预览 | 否 |
| POST | `/api/parsing/jd/preview` | 生成 JD 结构化预览 | 否 |
| GET | `/api/matching/config` | 返回 heuristic 版本、阈值、免责声明、技能字典摘要 | 否 |
| GET | `/api/jobs/{job_id}/match` | 计算确定性岗位匹配结果 | 否 |
| POST | `/api/jobs/{job_id}/match/explanation` | 让模型解释重新计算出的确定性事实 | 否 |

正式保存继续复用：

- `PUT /api/candidate`：用户确认覆盖当前简历，使用 `version` CAS。
- `POST /api/jobs`：用户确认创建岗位。
- `PATCH /api/jobs/{job_id}`：维护岗位正式数据。

## 5. Matching 规则

### 5.1 配置

```text
MATCH_HEURISTIC_VERSION=heuristic_v1
MATCH_STRONG_REQUIRED_COVERAGE=0.80
MATCH_REQUIRED_COVERAGE=0.60
```

这些阈值是可配置工程启发式，不是从招聘结果数据训练或校准出的标准。API 和界面固定展示：

```text
启发式规则，非录用概率或统计标准
```

### 5.2 等级

- 任一明确硬条件失败：`NOT_RECOMMENDED`
- 存在关键技能缺口，或岗位没有可计算的 required skills：`WEAK_MATCH`
- required coverage 达到 strong 阈值：`STRONG_MATCH`
- required coverage 达到 match 阈值：`MATCH`
- 其余：`WEAK_MATCH`

先判断硬条件，再看技能覆盖；高技能覆盖不能覆盖明确硬条件失败。

### 5.3 技能证据

每个岗位技能输出：

- 原始岗位技能
- 候选人原始技能或 `null`
- canonical skill
- skill category
- 是否命中
- 命中规则

验收示例中，候选人具有 `Python + FastAPI + Vue 3`，岗位要求 `Python + Django`：

- Python 命中
- Django 不命中
- required coverage = `1/2 = 0.5`
- FastAPI 与 Django 虽同属 `backend_framework`，但 canonical skill 不同，因此不能互相命中

## 6. 文件清单

### 后端新增

- `parsing/__init__.py`
- `parsing/extractors.py`
- `parsing/llm.py`
- `parsing/service.py`
- `matching/__init__.py`
- `matching/dictionary.py`
- `matching/service.py`
- `api/routers/parsing.py`
- `api/routers/matching.py`

### 后端修改

- `api/main.py`：注册 Phase 2 路由、支持注入测试 LLM、加载项目 `.env`、版本更新为 Phase 2。
- `core/container.py`：装配 Parsing 与 Matching Service。
- `core/errors.py`：增加外部模型服务 503 错误。
- `requirements.txt`：增加 PDF 与 multipart 依赖。
- `.env.example`：增加 DashScope、模型和 heuristic 配置。

### 前端修改

- `frontend/src/views/Candidate360View.vue`：TXT/PDF 提取、待确认简历预览、手工回退和显式保存。
- `frontend/src/views/JobCenterView.vue`：JD 待确认预览、硬条件/覆盖率/证据/缺口和可选解释。
- `frontend/src/api.ts`：支持 `FormData` 上传。
- `frontend/src/types.ts`：增加 Phase 2 类型。
- `frontend/src/styles.css`：增加解析与匹配视图样式。
- `frontend/src/views/LoginView.vue`：更新 Phase 2 产品说明。
- `frontend/package.json`：版本更新为 `2.0.0-phase2`。

### 测试、脚本与文档

- `tests/test_phase2.py`
- `scripts/run_phase2_acceptance.py`
- `scripts/run_phase2_live_llm_smoke.py`
- `scripts/release_check.py`
- `README.md`
- `Phase 2 实现报告.md`

## 7. 自动化测试

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

结果：

```text
26 passed, 2 warnings
```

Phase 2 新增 11 项测试，覆盖：

1. TXT 与文本型 PDF 提取成功且不落库。
2. 非 TXT/PDF、空文件和无文本扫描 PDF 被拒绝。
3. 简历结构化预览不覆盖正式 Candidate，显式 PUT 后才保存。
4. JD 结构化预览不创建 Job，显式 POST 后才保存。
5. 同输入与同 heuristic 配置返回完全相同结果和指纹。
6. FastAPI 不等价为 Django。
7. 硬条件失败优先于 100% 技能覆盖。
8. heuristic 版本和阈值可配置，且带非统计免责声明。
9. 模型解释只接收确定性事实，不改变匹配结果。
10. 无模型时手工维护与确定性匹配仍可用。
11. Matching 鉴权、候选人数据隔离和 4 页面边界。

两个 warning 均来自 FastAPI/Starlette TestClient 的上游弃用提示，不是业务测试失败。

## 8. 验收与构建结果

### Phase 1 回归验收

```text
PHASE 1 ACCEPTANCE: PASS
6/6 场景通过
tables=7, timezone=Asia/Shanghai, app_events=2
```

覆盖 Candidate、Job、Application/Event、幂等、CAS、Interview、Task、用户隔离和重启恢复。

### Phase 2 验收

```text
PHASE 2 ACCEPTANCE: PASS
6/6 场景通过
grade=WEAK_MATCH
required_coverage=0.5
```

覆盖浏览器预览不落库、显式确认保存、确定性复现、FastAPI/Django 负向案例、模型解释边界和 7 表边界。

### TypeScript 与生产构建

```text
vue-tsc --noEmit: PASS
Vite production build: PASS
29 modules transformed
CSS 12.79 kB (gzip 3.68 kB)
JS 104.39 kB (gzip 37.13 kB)
```

### 发布检查

```text
PHASE 2 RELEASE CHECK: PASS
7 schema tables
Parsing + deterministic Matching modules present
4 frontend pages
No deferred tables
Production bundle present
```

## 9. 真实模型冒烟

命令：

```powershell
.\.venv\Scripts\python.exe scripts\run_phase2_live_llm_smoke.py
```

测试仅发送合成简历和合成 JD，不发送真实个人信息。实际结果：

```text
PHASE 2 LIVE LLM SMOKE: FAIL - 模型鉴权失败，请检查 DASHSCOPE_API_KEY
```

已确认请求到达 DashScope，并收到 HTTP 401。当前进程配置和旧项目现存配置均无法通过鉴权；密钥没有被输出，也没有复制到 OfferFlow。需要在 `D:\offerflow-agent\.env` 填写有效的 `DASHSCOPE_API_KEY` 后重新执行上述命令。

该问题不影响：

- TXT/PDF 本地文本提取
- 手工维护当前简历和 JD
- 确定性 Matching
- Phase 1 全部业务功能

## 10. 当前边界

本阶段没有实现：

- ResumeVersion
- CandidateSkill 独立表
- AgentMemory
- PendingAction
- Agent/Tool Calling
- RAG
- Quality/AgentOps
- 企业官网抓取
- 自动投递
- Career Agent 第五页面

## 11. 已知问题与后续输入

1. **真实模型凭证已失效或不适用于当前 DashScope 端点。** 更新 `.env` 后运行 live smoke 复验即可，不需要改代码。
2. **扫描 PDF 不做 OCR。** 当前会明确提示先 OCR，符合 Phase 2 的 TXT/PDF 文本提取边界。
3. **技能字典是 v1 静态工程词典。** 未知技能使用 literal fallback，不会用 category 做宽泛命中；后续可基于真实 JD 逐步扩词，但不应在本阶段虚构同义词。
4. **heuristic 阈值没有统计依据。** 当前只用于排序和阅读辅助，不能表述为录用概率。
5. **解析预览没有 PendingAction 服务端持久化。** 刷新页面会丢弃未确认预览，这是本阶段有意保留的边界。

---

结论：除外部 DashScope 密钥鉴权需要用户更新外，Phase 2 代码、离线验收、回归测试、前端构建和发布边界均已完成。当前应停止并等待 Phase 2 验收确认，不进入 Phase 3。
