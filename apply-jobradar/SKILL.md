---
name: apply-jobradar
description: 旧版 JobRadar Skill 名称的兼容入口。仅当用户明确使用 $apply-jobradar 或要求从 JobRadar 找岗位时触发；立即转交 $fanhan-job-agent，并由 $apply-external-jobs 执行通用外部岗位流程。不得维护独立投递逻辑。
---

# JobRadar 旧入口

这是兼容旧 Prompt 的别名，不是独立产品入口。

1. 告诉用户：现在统一使用 `$fanhan-job-agent`，原请求不会丢失。
2. 调用 `$fanhan-job-agent` 整理真实材料和偏好；外部岗位步骤交给 `$apply-external-jobs`。
3. JobRadar 只作岗位发现源；实际申请遵循来源站点流程。
4. 不复制另一套选岗、隐私确认、提交或日志逻辑。
