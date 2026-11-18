# Grok Bot 内推

候选人明确授权后，把本次材料 POST 给 Grok Bot webhook。招聘负责人的 bot 接收后，再把候选人写入 Twenty 招聘 CRM。本 Skill 不调用招聘工作台的候选人入库接口，也不查询申请状态或招聘通知卡片。

读取真实开放岗位仍可以走只读的 `GET /api/public/jobs`，见 [泛函开放岗位](workbench-public-api.md)。岗位 ID 不是内推必填项。

## 命令

不要手写 HTTP 请求。使用 `scripts/grok_bot_referral.py`：

```bash
python3 <skill-root>/scripts/grok_bot_referral.py preview \
  .fanhan-job-agent/profile.json \
  .fanhan-job-agent/self-introduction.txt \
  .fanhan-job-agent/submission.json

python3 <skill-root>/scripts/grok_bot_referral.py record-consent \
  .fanhan-job-agent/profile.json \
  .fanhan-job-agent/submission.json \
  --confirmed

python3 <skill-root>/scripts/grok_bot_referral.py submit \
  .fanhan-job-agent/profile.json \
  .fanhan-job-agent/submission.json
```

有可选目标岗位时，给 `preview` 增加 `--job <岗位 JSON>`。没有岗位时省略 `--job`。

- `preview` 只在本地生成预览和状态文件，`network_writes` 必须是 0。
- `record-consent` 只有在候选人清晰同意下面的授权文案后才能带 `--confirmed`。拒绝、沉默或含糊答复都不得加这个参数，也不得运行 `submit`。
- `submit` 才发送网络请求。同一状态文件再次运行时复用同一次授权：已经送达则不再 POST；尚未送达则使用原来的提交标识，不新建第二次内推。

`scripts/workbench_client.py` 已停用，调用它只会失败。

## 操作者配置

Webhook 地址和发送密钥是操作者本机秘密。只从下面两处读取，优先环境变量：

- `FANHAN_GROK_BOT_WEBHOOK_URL`
- `FANHAN_GROK_BOT_WEBHOOK_KEY`

两项必须同时存在。都没有时，才读取与状态文件同目录、且未被 Git 跟踪的 `.fanhan-job-agent/grok-bot-referral.json`：

```json
{
  "webhook_url": "<从例程面板复制的地址>",
  "webhook_key": "<从例程面板复制的密钥，不要带 Bearer 前缀>"
}
```

密钥从 Grok Bot 例程面板「天才职业顾问内推接收」复制。缺失或只配置了一项时，停止并告诉操作者在本机设置。不要向候选人索取地址或密钥，不要把它们写进仓库、README、测试、示例或 Git 历史。建议把该 JSON 设为仅本用户可读。

请求固定为：

- `POST` JSON
- `Authorization: Bearer <密钥>`
- `Content-Type: application/json`
- HTTP 200 表示送达。不要解析或编造业务响应体。
- 非 200 或无法连接时，用同一份字节自动重试一次。仍然失败就如实说明没有送达，保留原来的提交标识。

## 授权文案

预览后必须逐字展示：

> 我同意将上述求职资料发送给泛函，用于候选人档案管理、岗位匹配和招聘团队人工审核。资料将保存在泛函的 Twenty 招聘 CRM。我之后可以要求停止推荐或删除档案。

这句会原样放进 `consent.text`。`consent.confirmed` 必须为 true。

## 请求体

未知字段省略，不编造。`type`、`source`、`submitted_at`、`idempotency_key`、`consent`、`candidate` 和 `resume_filename` 在可发送时都会出现。

```json
{
  "type": "skill_referral",
  "source": "genius-career-advisor-skill",
  "submitted_at": "ISO-8601 时间",
  "idempotency_key": "稳定的本地提交标识，不出现在普通输出里",
  "consent": {
    "confirmed": true,
    "text": "候选人同意的原句",
    "confirmed_at": "ISO-8601 时间"
  },
  "candidate": {
    "name": "",
    "email": "",
    "phone": "",
    "wechat": "",
    "city": "",
    "employment_type": "full_time | internship | unknown",
    "desired_locations": [],
    "work_mode": "",
    "direction": "",
    "skills": [],
    "portfolio": [],
    "current_title": "",
    "current_company": "",
    "years_experience": ""
  },
  "target_role": {
    "company": "",
    "title": "",
    "job_id": "",
    "source": ""
  },
  "self_introduction": "",
  "resume_text": "能提取到当前岗位专用 PDF 文本时附上",
  "resume_filename": "",
  "resume_pdf_base64": "仅当确认过的 PDF 不超过约 1.5 MB",
  "notes": ""
}
```

- 邮箱，或电话／微信，至少要有一项。电话只在整段联系方式就是电话号码时写入 `phone`，否则写入 `wechat`，不拆成两个事实。
- `正式`、`全职`、`正职` 写成 `full_time`，`实习` 写成 `internship`。候选人还没确认时写 `unknown`。明确说两者都可以时省略该字段。
- `target_role` 整体可选。缺少泛函 `job_id` 不阻止发送。外部链接不要放进 `job_id`。
- PDF 超过约 1.5 MB 时省略 `resume_pdf_base64`。能提取文本时仍发送 `resume_text` 和 `resume_filename`。
- 当前岗位专用 PDF 必须来自 `.fanhan-job-agent/outbox/`，并且是候选人检查同名 HTML 后导出的文件。不要上传原始简历。

## 结果

HTTP 200 之后，只告诉候选人材料已经交给泛函招聘团队，将保存在 Twenty 招聘 CRM。不要报告工作台申请号或旧匹配分，也不要自动开始面试辅导。

命令输出、普通日志和对话里都不要出现 webhook 密钥或 `idempotency_key`。提交状态保存在 `.fanhan-job-agent/submission.json`，权限为仅本用户可读写。
