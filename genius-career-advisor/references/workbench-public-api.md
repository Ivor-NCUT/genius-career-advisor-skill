# 团体岗位与泛函开放岗位（只读，可选）

团体岗位和泛函开放岗位都在当前的 Twenty 招聘工作台上。只有候选人明确要求把它们纳入本轮找岗时才读取本文件，并运行：

```bash
python3 <skill-root>/scripts/fanhan_open_jobs.py
```

默认找岗不运行这条命令，也不读取本文件。

## 不要查询完整 Twenty

不要登录 Twenty，也不要查询完整的 Twenty API。完整接口会碰到候选人、内部备注、招聘评语、流程状态和其他不属于岗位说明的数据。不要从本技能使用有权限的工作台 token。

## 唯一允许的列出方式

列出团体岗位的唯一方式，是已经为 `FANHAN_PUBLIC_JOBS_URL` 准备好的、不含密钥、只含岗位说明的 HTTPS JSON。操作者只在本机设置这个环境变量，不要把地址写进仓库。脚本不发送 `Authorization`，地址里也不带账号、查询参数或密钥。

每条岗位只使用下面这些字段，不要多读其他字段。未知字段留空，不推断：

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

脚本只采用同时有公司和职位的记录。响应不是这份 JSON，或请求失败时，记为 `unavailable`。不要把这种情况说成已经搜过而且没有岗位，也不要据此编一份清单。不要把已经停止招聘的公司说成当前开放岗位。

岗位 ID 只用于展示和匹配。候选人要求把材料交给泛函时，没有岗位 ID 也不阻止发送。没有这个要求时，不要因为读到了岗位就进入内推。

## 契约没配好时

没有配置 `FANHAN_PUBLIC_JOBS_URL` 时，脚本不访问网络，并返回 `source_status=unavailable`、`reason=public_contract_missing`。告诉候选人现在还不能列出团体岗位。不要改口说成「没有岗位」，不要编一份清单，也不要用有权限的工作台 token 补查。

列出岗位以外的事不要从本文件延伸。不要调用 `scripts/workbench_client.py`。候选人明确要求把材料交给泛函时，改用 `scripts/grok_bot_referral.py`。
