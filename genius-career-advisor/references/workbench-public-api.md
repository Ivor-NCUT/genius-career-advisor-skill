# 泛函开放岗位（只读，可选）

只有候选人明确要求把泛函纳入本轮找岗时才读取本文件。默认找岗不调用这里的接口。

运行 `python3 <skill-root>/scripts/fanhan_open_jobs.py`。没有配置公开地址时，它返回 `source_status=unavailable`、`reason=public_contract_missing`，并且不访问网络。把这个结果告诉候选人：现在还不能列出泛函开放岗位。不要改口说成“没有岗位”，也不要自己补一份清单。

## 当前缺口

当前招聘系统是 Twenty 工作台，地址为 `https://43.136.55.30`（公开 `client-config` 的 `appVersion` 为 Twenty `2.55.0`）。2026-11-19 复核：

- `GET /api/public/jobs` 在浏览器请求下返回 Twenty 前端 HTML，不是岗位 JSON。带 `Accept: application/json` 时返回 404。
- `GET /rest/jobs` 返回 403，`Missing authentication token`。
- `POST /graphql` 未认证时返回 `Authentication required`。
- 公开站点 `https://fanhan-hire.vip/` 返回 503。

因此还没有一条不携带密钥就能读取当前开放岗位的契约。不要把工作台 API key、Bearer token 或服务端密钥写进仓库、技能或对话。

旧地址 `https://fanhan-workbench.zeabur.app/api/public/jobs` 仍会返回一份过期 JSON。脚本拒绝这个主机。不要把它的公司或职位说成当前开放岗位。

## 准备好的公开读取形状

将来的公开接口必须是不带账号、查询参数和密钥的 HTTPS JSON。操作者只在本机设置 `FANHAN_PUBLIC_JOBS_URL`，不要把地址写进仓库。脚本不发送 `Authorization`。

响应使用下面的形状。未知字段留空，不推断：

```json
{
  "jobs": [
    {
      "id": "稳定 ID",
      "company": "公司",
      "title": "职位",
      "summary": "短摘要",
      "description": "完整 JD",
      "city": "城市",
      "work_type": "全职或实习",
      "work_mode": "到岗方式，未知则留空",
      "url": "岗位公开链接"
    }
  ]
}
```

脚本只采用同时有公司和职位的记录。公司或职位中出现已停止招聘的 Eazo 时，该条被去掉，并且不会出现在输出里。HTML、非 JSON 或 HTTP 错误都记为 `unavailable`，不能当成空清单以外的成功。

岗位 ID 只用于展示和匹配。候选人要求把材料交给泛函时，没有岗位 ID 也不阻止发送。没有这个要求时，不要因为读到了岗位就进入内推。

## 已停用

下面的入库和状态契约已经停用。不要调用，不要轮询，也不要把它们的返回值说成内推成功：

- `POST /api/public/candidate-files`
- `POST /api/public/candidate-applications`
- `GET /api/public/candidate-applications/<申请 ID>`
- 申请处理状态、匹配分，以及招聘话题群通知卡片

`scripts/workbench_client.py` 只会拒绝执行。候选人明确要求把材料交给泛函时，改用 `scripts/grok_bot_referral.py` 的 `preview`、`record-consent` 和 `submit`。
