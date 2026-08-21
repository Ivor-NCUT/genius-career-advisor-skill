# 工作台接入审计

本文件对应 GitHub Issue #11，是后续 Skill 接入泛函招聘工作台的代码事实基线。

## 核验范围

- 产品基线：飞书《泛函求职投递 Skill｜V1 产品、测试与开发文档》revision 4。
- 工作台仓库：`Ivor-NCUT/ai-recruiting-workbench`。
- 核验提交：`3f3e468d3f0ef84b661db590b9585eaf554bb11e`。
- 数据边界：只使用认证业务 API；不得直接访问 SQLite，也不得回退到飞书多维表格。

## 结论

工作台已有候选人幂等入库、候选人评分存储、岗位库、岗位中心匹配、匹配审核和单岗位投递状态机，可以复用。Issue #326/#327 与 #331/#332 已提供限流、幂等、要求明确授权的候选人公开入口；Issue #333/#334 已允许候选人回读本人本次申请的脱敏匹配结果。

候选人首次入库通知已由工作台 PR #339 补齐：首次授权入库会创建单一内部通知队列记录，冻结消息与 PDF 哈希；安全失败最多自动重试三次，结果未知转人工处理且不会制造第二次候选人入库。三天版剩余 P0 是三名真实候选人的端到端验收，不能用模拟材料替代。

## 可直接复用的能力

| 能力 | 工作台接口或实现 | 关键语义 |
|---|---|---|
| 健康检查 | `GET /healthz` | 数据库未 ready 时停止写入。 |
| 候选人幂等写入 | `POST /api/candidates` | 使用 `Idempotency-Key`；重复请求返回原候选人，不新增记录。 |
| 候选人读取与更新 | `GET /api/candidates/:id`、`PATCH /api/candidates/:id` | 更新候选人事实后会清空旧候选人评分，避免陈旧分数。 |
| 候选人文件 | `POST /api/candidate-files` | 已有受认证文件上传与分片上传；不能通过公开 Skill 暴露服务 Token。 |
| 候选人评分保存 | `POST /api/candidate-scores/batch` | 只保存可信评分结果，不在工作台内计算该评分。 |
| 岗位库 | `GET /api/jobs`、`GET /api/jobs/:id` | 可读取泛函真实开放岗位。 |
| 岗位中心匹配 | `POST /api/match-runs`、`GET /api/match-runs/:id`、`GET /api/matches` | Connector 对一个岗位给候选人排序，结果带算法版本和证据。 |
| 匹配审核 | `PATCH /api/matches/:id` | 状态为 `pending`、`approved`、`rejected` 或 `waiting_materials`；记录审核时间和备注。 |
| 单岗位投递记录 | `/api/job-applications` | 已有幂等创建、确认哈希、提交状态、结果未知和人工恢复。 |

## 字段映射

候选人最小写入字段如下。产品要求的“原始简历、有效联系方式、明确授权”必须在 Skill 或新的窄入库接口中先校验；当前 `POST /api/candidates` 自身只要求姓名、联系方式或文件至少一项。

| 产品字段 | 工作台字段 | 说明 |
|---|---|---|
| 姓名 | `name` | 可为空，但三天真实候选人测试应要求提供。 |
| 邮箱 | `email` | 身份去重字段之一。 |
| 手机或微信 | `phoneOrWechat` / `phone_or_wechat` | 身份去重字段之一。 |
| 当前城市 | `city` | 不能据此推断期望地点。 |
| 实习或正职 | `workType` / `work_type` | 参与现有岗位匹配门禁。 |
| 目标方向 | `direction` | 用于候选人匹配文本。 |
| 技能 | `skills` | 字符串数组。 |
| 作品集与链接 | `portfolio` | 字符串数组。 |
| 结构化职业事实 | `careerFacts` / `career_facts` | 保存有证据的事实；未知值保持未知。 |
| 来源 | `referrerName` / `referrer_name` | 三天版使用固定来源 `fanhan-job-application-skill`。 |
| 主档状态 | `status` | 现有值是 `needs_review`、`active`、`do_not_contact`、`archived`，不是产品的资料完整度状态。 |
| 原始简历文本 | `resumeText` | 与文件 ID 一起进入候选人版本。 |
| 原始文件 | `fileIds` | 先通过受认证文件接口上传。 |

产品的 `待补充` / `可匹配` 是资料完整度，不应覆盖工作台现有主档状态。最小实现先写入 `careerFacts.profile_completeness`；如果工作台需要筛选和统计，再新增独立列与查询参数。

## 两套评分不能混用

### 候选人综合评分

`POST /api/candidate-scores/batch` 保存外部可信 Skill 产生的候选人综合评分。必填字段包括：

- `candidate_id`
- `algorithm_version`
- `benchmark_scores.unified`
- `benchmark_scores.engineering`
- `benchmark_scores.product`
- `benchmark_scores.growth_operations`
- `benchmark_scores.design`
- `benchmark_scores.creative`
- `benchmark_scores.commercial`
- `benchmark_scores.people_recruiting`
- `five_good.score`，范围 0–55
- `talent_value`
- `evidence_coverage`，范围 0–1

工作台只校验和保存这些结果，没有在本仓库内实现该综合评分算法。新候选人不能因为入库成功就被描述为“已经完成综合评分”。

### 候选人与岗位匹配评分

工作台内置匹配算法版本为：

`agentic-matching-lite-v0.2-no-training-engagement-gate`

总分计算为：

`round(0.25 × keyword_score + 0.30 × semantic_score + 0.25 × rule_score + 0.20 × llm_review_score)`

实习与正职兼容性先于分数：不兼容时分数封顶并输出风险。匹配结果还包含 `evidence`、`risks`、`reason`、`hard_filter_summary` 和 `algorithm_version`。

Skill 不复制这套公式。公开候选人提交完成后，工作台会保存该候选人 × 岗位的匹配记录，并通过带本地 `client_token` 的状态查询返回脱敏结果。由于精确计算需要读取简历，隐私顺序固定为：授权前只在本地检查用户明确硬限制并给出定性证据；授权入库后再展示工作台保存的精确分数。若要在授权前得到数值评分，必须另设“一次性上传用于匹配”的独立授权与留存规则。

## 审核语义

工作台现有审核是“候选人与岗位的匹配审核”，不是候选人全局准入审核。它已经覆盖：

- `pending`：待审核
- `approved`：审核通过
- `rejected`：审核不通过
- `waiting_materials`：等待材料
- 审核备注与审核时间

三天版只要围绕一个泛函真实岗位闭环，可以直接复用匹配审核，不新增候选人全局审核表。只有将来确实需要“该候选人对所有岗位统一禁入或通过”时，才新增候选人级审核状态。

## 通知语义

`/api/candidate-ingest/notifications/*` 和每日摘要只面向已经进入企业投递链路的候选人，用于发送面试、拒绝、岗位关闭等状态变化。它们不能复用为内部首次入库通知。

首次入库通知需要工作台新增独立队列，至少保存：

- 候选人 ID
- 首次入库事件键
- 资料完整度
- 发送状态
- 尝试次数
- 飞书消息 ID
- 最后错误
- 创建与更新时间

候选人写入成功后创建一次通知；通知失败不得回滚候选人；补齐资料不得再创建第二条首次通知。

## 身份与安全缺口

现有 `recruiting-database-crud` 使用 `WORKBENCH_DATABASE_API_TOKEN`，可访问大量私有业务 API。现有候选人入库链路使用另一个 `WORKBENCH_CANDIDATE_INGEST_TOKEN`。两者都属于服务端秘密，不能写入开源仓库、Skill 文件或候选人的本地配置说明中。

因此后续开发必须先选择一个窄入口：

1. 工作台签发短期、单用途候选人入库码；或
2. 工作台提供限流、幂等、最小字段的公开候选人自助提交接口。

不接受“把共享 Token 放进 Skill”作为三天版捷径。

## 后续 Issue 依赖顺序

1. 候选人自助入库身份、最小上传入口和匹配结果回读已完成。
2. 下一步补首次入库通知队列和飞书发送状态。
3. Skill 接入定制材料与真实候选人验收。
4. Bonjour、Watcha 和 JobRadar 的外部流程继续复用同一套安全骨架。

## 代码级验证

在上述工作台提交执行：

```bash
node --test \
  tests/matching/engine.test.js \
  tests/candidates/candidates.test.js \
  tests/match-review/http.test.js \
  tests/cloud/job-applications.test.js
```

这组测试验证候选人幂等与评分存储、岗位匹配算法、审核 API 和投递状态机。它不等于生产环境端到端验收；真实写入、飞书话题群和候选人数据必须在相应 Issue 中单独验证。
