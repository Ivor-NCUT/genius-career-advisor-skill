# 本地职业档案契约

文件位置：当前工作区 `<workspace>/profile.json`。`<workspace>` 由 `scripts/workspace.py resolve` 决定。原始材料不进入该 JSON，只保存路径、结构化事实和证据位置。

```json
{
  "schema_version": "fanhan-career-profile-v1",
  "resume": {
    "path": "/path/to/resume.pdf",
    "sha256": "unknown"
  },
  "identity": {
    "name": "unknown"
  },
  "career_document": {
    "path": "职业经历.md"
  },
  "application_resume": {
    "path": "unknown"
  },
  "contact": {
    "email": "unknown",
    "phone_or_wechat": "unknown"
  },
  "intent": {
    "target_roles": [],
    "employment_type": "unknown",
    "preferred_locations": [],
    "remote_preference": "unknown",
    "relocation_preference": "unknown",
    "available_from": "unknown",
    "work_authorization": "unknown",
    "salary_expectation": "unknown",
    "target_industries": [],
    "company_preferences": []
  },
  "education": {
    "status": "unknown",
    "items": []
  },
  "core_experiences": {
    "status": "unknown",
    "items": []
  },
  "career_consultation": {
    "representative_achievement": {
      "summary": "候选人确认后的长期可复用摘要",
      "confirmed": true,
      "evidence": ["候选人明确回答或对材料提取结果的明确确认"]
    },
    "personal_contribution": {},
    "challenge_and_decision": {},
    "result_evidence": {},
    "learning_and_growth": {}
  },
  "optional_links": [],
  "evidence": {},
  "consent": {
    "confirmed": false,
    "confirmed_at": "unknown",
    "material_version": "unknown",
    "idempotency_key": "unknown"
  }
}
```

## 枚举

- `employment_type`：`internship`、`full_time`、`either`、`unknown`
- `remote_preference`：`accept`、`reject`、`conditional`、`unknown`
- `relocation_preference`：`accept`、`reject`、`conditional`、`unknown`
- `work_authorization`：`unknown`，或候选人明确拥有的工作许可字符串数组。
- `education.status` / `core_experiences.status`：`known` 或 `unknown`。明确确认“没有”也属于 `known`，`items` 可以为空。

## 证据

每个非未知的可匹配字段都要在 `evidence` 中留下至少一条来源说明。键使用字段路径，例如：

```json
{
  "evidence": {
    "identity.name": ["resume.pdf 第 1 页"],
    "contact.email": ["resume.pdf 第 1 页"],
    "intent.preferred_locations": ["候选人于本轮明确回答：上海、杭州"],
    "education": ["resume.pdf 教育经历"],
    "core_experiences": ["resume.pdf 项目经历"]
  }
}
```

`career_document.path` 必须指向本技能根据当前材料生成或更新的非空 `职业经历.md`。`profile.json` 只是机器可读索引，不能代替职业主档。

## 首次职业咨询

进入找岗前，必须完成五个长期复用维度：代表性成果、个人贡献、困难与判断、结果证据、学习与成长。每个维度都必须包含非空 `summary`、`confirmed=true` 和至少一条 `evidence`。

问题文字要结合候选人材料中最有潜力的一段经历生成，不照着字段名机械提问；一次只问一个。材料已经覆盖某个维度时，先给出提取摘要，让候选人确认或纠正，不能直接替候选人确认。确认后的完整内容同步写入 `职业经历.md`，`profile.json` 只保存短摘要与证据位置。

候选人说不清或不知道怎么描述，只说明这一问还没法答，不代表这段经历不存在，不得从 `职业经历.md` 或简历里删除。立刻改问当时的具体动作和事后情况，并用材料里已有的原句当线索；不要一上来问「最后交付了什么」。确定不了的部分在摘要里标「未核实」，只保留已经说清的内容，不编造结果。把这份边界给候选人看过并得到确认后，才能把该维度标为 `confirmed=true`。`confirmed=true` 只表示对方确认了已经说清的部分。完整问法见 [说不清时换问法](career-assets.md#说不清时换问法)。

`application_resume.path` 只在用户检查同名可编辑 HTML、亲自导出并确认当前岗位专用 PDF 后填写；它不能指向原始简历、仅做格式转换的 PDF 或没有同名 HTML 的 PDF。泛函内推和外部申请只使用该文件。

只记录来源位置或候选人确认，不复制大段简历正文。当前城市不是期望地点证据；模型推断不是远程或搬迁意愿证据。

## 两种状态彼此独立

- `profile_status=待补充/可匹配`：表示基础材料和首次五维职业咨询是否都足以进入岗位推荐。
- `ingest_ready=true/false`：只表示是否具备原始简历、有效联系方式和可审计授权。内推授权还会写入 `text_version`，必须对应当前授权文案。不要在对话或日志里展示 `idempotency_key`。

因此，“待补充但已授权”的候选人可以把材料交给泛函，但不能进入岗位推荐；“可匹配但未授权”的候选人可以继续本地找岗、定制简历和外部申请，只是不能把材料上传给泛函。未授权是默认状态。找岗前不要索取泛函授权。
