# 泛函开放岗位（只读，可选）

只有候选人明确要求把泛函纳入本轮找岗时才读取本文件。默认找岗不调用这里的接口。

筛选岗位时运行：

```bash
python3 <skill-root>/scripts/fanhan_open_jobs.py --query '<目标岗位关键词>'
```

例如搜索 `Agent工程师`。没有配置公开地址时，它返回 `source_status=unavailable`、`reason=public_contract_missing`，并且不访问网络。把这个结果告诉候选人：现在还不能列出泛函开放岗位。不要改口说成“没有岗位”，也不要自己补一份清单。

操作者把 Twenty 公开岗位服务的 HTTPS 地址设为 `FANHAN_PUBLIC_JOBS_URL`。地址本身不能带账号、查询参数或密钥。脚本只追加 `q`，并且不发送 `Authorization`。不要把地址、工作台 API key 或服务端密钥写进仓库、技能或对话。

## 只返回对外岗位

服务端只查询正在招聘的岗位，响应只能是：

```json
{
  "jobs": [
    {
      "company_name": "公司名",
      "job_name": "职位名",
      "job_jd": "职位 JD"
    }
  ]
}
```

`job_jd` 为空时可以省略。脚本丢掉除此之外的所有字段，包括候选人、内部备注、沟通记录、招聘偏好、群聊、来源猎头和检索 JSON，并且不会把这些内容打印出来。不要改用 `/graphql`、`/rest` 或带密钥的工作台接口去补这些字段。

公司名或职位名缺失的记录不采用。公司或职位中出现已停止招聘的 Eazo 时，该条被去掉，并且不会出现在输出里。HTML、非 JSON 或 HTTP 错误都记为 `unavailable`，不能当成空清单以外的成功。

旧地址 `https://fanhan-workbench.zeabur.app/api/public/jobs` 仍会返回一份过期 JSON。脚本拒绝这个主机。不要把它的公司或职位说成当前开放岗位。

没有岗位 ID 也不阻止后续步骤。读到公开岗位不等于候选人同意把材料交给泛函。

## 已停用

下面的入库和状态契约已经停用。不要调用，不要轮询，也不要把它们的返回值说成内推成功：

- `POST /api/public/candidate-files`
- `POST /api/public/candidate-applications`
- `GET /api/public/candidate-applications/<申请 ID>`
- 申请处理状态、匹配分，以及招聘话题群通知卡片

`scripts/workbench_client.py` 只会拒绝执行。候选人明确要求把材料交给泛函时，改用 `scripts/grok_bot_referral.py` 的 `preview`、`record-consent` 和 `submit`。
