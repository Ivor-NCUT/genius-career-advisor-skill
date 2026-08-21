# JD 定制材料契约

定制过程使用 `.fanhan-job-agent/tailored-proposal.json`。针对性提问完成后，第一份候选人可见成稿必须直接生成到 `.fanhan-job-agent/outbox/` 下的可编辑 HTML；原始简历永远只读。

```json
{
  "schema_version": "fanhan-tailored-material-v1",
  "job": {
    "id": "工作台岗位 ID 或外部岗位稳定链接",
    "company": "目标公司",
    "title": "岗位名称"
  },
  "artifact_stem": "候选人姓名-目标公司-目标岗位-YYYYMMDD-v1",
  "consultation": {
    "status": "completed",
    "questions": [
      {
        "id": "question-1",
        "question": "结合 JD 和职业主档生成的具体问题",
        "jd_basis": ["JD 中触发该问题的具体要求"],
        "profile_basis": ["职业经历.md 中值得补强的经历位置"],
        "answer_summary": "候选人确认后的回答摘要",
        "confirmed": true,
        "used_in_change_ids": ["change-1"]
      }
    ]
  },
  "sections": [
    {
      "heading": "相关经历",
      "content": "定制后的正文",
      "change_ids": ["change-1"]
    }
  ],
  "changes": [
    {
      "id": "change-1",
      "type": "rewrite",
      "summary": "把已有经历改写为岗位相关表达",
      "jd_basis": ["JD 中的具体要求或位置"],
      "fact_evidence": ["简历中的证据位置或候选人明确回答"],
      "confirmation": "not_required"
    }
  ]
}
```

## 完整性与文件名

- 选岗后、生成简历前必须完成 1–2 个针对当前 JD 的问题；一次只问一个。每个问题都要同时说明 `jd_basis` 和 `profile_basis`，回答必须由候选人确认，并通过 `used_in_change_ids` 进入至少一项真实简历变更。缺少咨询记录、问题超过两个或回答未用于成稿时，`material_gate.py` 必须拒绝生成文件。
- 针对性回答先同步回长期 `职业经历.md` 和 `profile.json`，再派生当前岗位简历。不能只改措辞而丢掉本轮确认的新证据。
- `sections` 必须构成一份完整可投递简历，不能只包含零散修改建议。
- 修改建议先在聊天中向候选人展示，再进入成稿。
- `artifact_stem` 必须由职业档案中的候选人姓名和当前岗位的公司、职位生成，格式为 `姓名-目标公司-目标岗位-YYYYMMDD-vN`。
- 原简历文件名中的公司不能继承到新版本，除非它就是当前目标公司。
- HTML 页面右上角提供“导出 PDF”；用户检查或编辑后，编辑器冻结点击时的当前页面内容并按同一 `artifact_stem` 下载 PDF。
- HTML 生成后必须立即在 Codex 侧边栏展示。用户回传导出的 PDF 后，必须通过 `material_gate.py --accept-exported-pdf` 原字节接收到同名 outbox PDF；不得从磁盘 HTML、旧 PDF、Headless Chrome 或其他脚本重新生成替代文件，也不得在接收成功前填写 `profile.application_resume.path`。
- 工作台和外部投递门禁必须同时检查同名 HTML，并确认 PDF 是内置编辑器的原始导出；只有 PDF、没有同名可编辑 HTML、PDF 早于 HTML，或 PDF 是后续重新生成的替代文件时必须拒绝。
- PDF 确认前做两遍检查：先看页面断行、分页、空白和信息层级，再读取 PDF 文本层，核对姓名与联系方式、阅读顺序、JD 关键词和本轮咨询新增内容。文本层无法读取时明确标记“ATS 解析未验证”，不得只凭页面看起来正常就宣称兼容 ATS。

## 变更类型

- `reorder`：只调整已有内容顺序，不改变事实；`confirmation=not_required`。
- `rewrite`：只改写已有事实，不新增数字、职责、技能、时间或成果；`confirmation=not_required`。
- `fact_addition`：加入原材料没有、但候选人补充的新事实；必须先逐项展示并取得确认。
- `fact_change`：改变原材料中的事实含义；必须先逐项展示并取得确认。

`fact_addition` 和 `fact_change` 只有在候选人明确确认后才能写为 `confirmation=confirmed`，同时记录 `confirmed_at`。拒绝、含糊答复和沉默均保持 `pending` 或从提案中删除，不能进入成稿。

## 依据规则

- 每项变更都必须同时有非空 `jd_basis` 和 `fact_evidence`。
- 每个成稿章节必须引用至少一个变更；每项变更也必须被成稿章节引用。
- 事实证据只写来源位置或候选人确认，不复制大段原始简历。
- 脚本只负责结构门禁，语义判断仍由 Agent 对照真实简历与 JD 完成；不确定时标为未知，不做润色推断。
