# 工作台公开接口契约

基线：`Ivor-NCUT/ai-recruiting-workbench` Issue #326 与 #331。默认服务地址为 `https://fanhan-workbench.zeabur.app`；如用户或测试环境提供 `FANHAN_WORKBENCH_URL`，优先使用该地址。

## 安全边界

- Skill 只调用 `/api/public/*` 候选人自助入口，不携带 `WORKBENCH_DATABASE_API_TOKEN` 或 `WORKBENCH_CANDIDATE_INGEST_TOKEN`。
- `client_token` 是候选人本地生成的随机会话标识，只用于幂等和查询本人本次申请；不得打印、提交到 Git 或写入普通投递日志。
- 文件上传和申请创建都必须发生在候选人明确授权之后。

## 请求顺序

1. `GET /healthz`：未 ready 时停止写入。
2. `GET /api/public/jobs`：读取脱敏后的真实开放岗位。
3. `POST /api/public/candidate-files?name=<文件名>`：请求体必须是用户确认过的当前岗位专用 PDF，取自 `profile.application_resume.path`；禁止上传 `profile.resume.path` 指向的原始简历。`Content-Type: application/pdf`，最大 10 MB。
4. `POST /api/public/candidate-applications`：JSON 字段如下。

```json
{
  "job_id": "真实岗位 ID",
  "file_id": "上传返回的文件 ID",
  "client_token": "本地随机会话标识",
  "portfolio_url": "可选的 HTTP(S) 链接",
  "self_introduction": "候选人确认过的自荐说明",
  "candidate_name": "本地职业档案中经候选人确认的姓名",
  "candidate_email": "有效邮箱；与联系方式至少提供一项",
  "candidate_phone_or_wechat": "电话或微信；与邮箱至少提供一项",
  "consent_confirmed": true
}
```

候选人确认身份与当前岗位专用 PDF 一起绑定到本地私有提交状态和授权。工作台先校验这些字段，并在模型漏抽取身份时作为确定性回退；它们不能绕过授权，也不会出现在 `preview` 的用户可见明文结果中。旧版提交状态必须重新执行 `preview`，不得直接复用。

5. `GET /api/public/candidate-applications/<申请 ID>`，请求头 `X-Application-Client-Token` 使用同一会话标识，读取 `processing`、`completed` 或失败状态。

不要手写请求。主 Skill 使用 `scripts/workbench_client.py` 的 `preview`、`record-consent`、`submit` 和 `status` 子命令。`preview` 不发网络写请求；`submit` 会在任何网络请求之前核对当前 PDF 哈希、授权版本、授权时间、稳定会话标识和最低入库条件。同一状态文件重复运行 `submit` 只查询既有申请。

## 结果解释

- 重复请求返回同一个申请，不代表创建第二名候选人。
- `completed` 表示候选人材料已完成工作台处理；资料待补充时可以没有岗位匹配。
- 只有资料可匹配时才生成 `pending` 匹配审核，绝不自动批准或发送给企业。
- `match` 非空时只包含本次候选人 × 岗位的脱敏结果：`score`、`algorithm_version`、`reason`、`hard_filter_summary`、`keywords`、`evidence` 和 `risks`。它是工作台保存的真实结果，只能在候选人授权提交后回读，不得在 Skill 中重算。
- `notification` 只返回脱敏的内部首次入库通知状态：`pending`、`sent`、`manual` 或 `unknown`，以及尝试次数和是否需要人工处理。它不包含飞书群 ID、消息 ID 或内部错误。
- `manual` 和 `unknown` 都表示泛函内部正在处理；Skill 只向用户说明状态，不得更换会话标识、重传简历或新建第二次申请。

公开岗位当前稳定字段是 `id`、`company`、`title`、`summary`、`description`、`category`、`city`、`work_type`、`salary` 和 `required_skills`。`work_mode`、`relocation_required`、`required_start_date` 和 `work_authorization` 缺失时必须标记未知，不能推断为符合。
