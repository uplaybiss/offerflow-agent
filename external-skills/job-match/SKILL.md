---
name: job-match
description: 基于 OfferFlow 已保存的 JD、Candidate 和简历事实做可解释岗位匹配。
---

# /job-match

只分析用户已保存到 OfferFlow 的岗位，不搜索互联网，也不创建或修改业务数据。

## 必须复用

- 用 `search_jobs` 解析用户所指岗位；有多个同名岗位时先澄清。
- 用 `analyze_job_match` 读取现有硬条件与确定性 Matching 结果。
- 需要跨岗位汇总时用 `analyze_skill_gaps`，不要另建 Matching Engine。
- 需要核对简历表达时用 `analyze_resume_for_job`。

## 分析规则

1. 先拆解并展示硬条件，再看核心职责、必备技能和加分项。
2. 结论只使用 Candidate、Base Resume、ResumeVersion 与用户确认事实。
3. 使用五种状态：`已匹配`、`表达缺口`、`证据不足`、`真实缺口`、`待确认`。
4. Matching 中“未找到技能”只说明当前事实未覆盖；除非用户已确认不会，否则不要擅自升级为真实缺口。
5. JD 只能是岗位要求，不能直接成为 Candidate Fact；团队成果不能自动算作个人成果。
6. 不输出伪精确匹配百分比，不把启发式等级解释成录用概率。

## 输出

依次给出：岗位结论、要求—证据矩阵、硬条件、最多五项优先补强、投递建议与待确认信息。每个“已匹配”或“表达缺口”都要说明证据位置；没有证据时明确写“未提供”。
