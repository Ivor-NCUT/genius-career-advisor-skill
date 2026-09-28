---
name: apply-external-jobs
description: 从内置岗位来源快照筛选渠道、搜索岗位，并在用户选岗和确认岗位专属简历后使用 EgoLite 填写与提交网申、记录结果。只投用户选中的岗位；不得绕过登录、验证码、付费限制或猜测申请事实。
---

# 外部招聘平台投递

这是 `$fanhan-job-agent` 的内部执行 Skill，不是另一个产品入口。开始前读取 [执行契约](references/v1-contract.md)；进入申请页时读取 [EgoLite 网申执行](references/egolite-application.md)；执行验收时再读取 [test record template](references/test-record-template.md)。

## 对话风格

- 默认像微信对话：先说结论，通常 1–3 个短句，每轮只推进一个问题或动作。
- 不复述长背景；需要用户接管时，只说当前卡点、要做的动作和完成后如何继续。
- 个人数据发送范围、失败状态和最终提交摘要必须完整，不得为了简短而省略。

## 工作流

1. 返回 `$fanhan-job-agent`，确认 `$职业资产` 已生成非空 `.fanhan-job-agent/职业经历.md`、`.fanhan-job-agent/profile.json` 和与当前档案哈希一致的 `profile-status.json`，并已分别建立 `.fanhan-job-agent/用户求职记忆.md` 与 `.fanhan-job-agent/Agent平台执行记忆.md`。状态不是 `可匹配` 时停止找岗并补齐最小缺口；不得用原始简历直接开始搜索。
2. 运行 `python3 <skill-root>/scripts/source_catalog.py --query '<目标岗位 地点 办公方式>' --limit 5`，展示返回的 3–5 个来源、访问门槛、推荐原因和风险；等待用户确认或调整。来源快照来自泛函已核对的岗位来源表，不在运行时访问私有飞书表格。
3. 使用 `scripts/application_log.py duplicate` 检查工作区 `.fanhan-job-agent/external-applications.jsonl`；命中成功记录时跳过，除非用户明确要求重投。
4. 读取 `Agent平台执行记忆.md` 中与已确认来源相关的记录。确认列表包含 Bonjour、Watcha 或 JobRadar 时运行 `external_jobs.py` 并只采用已确认来源的结果；其他来源最多依次打开已确认的页面。岗位发现不得依赖浏览器反复重试；单一来源失败不得阻塞其他来源。JobRadar 未获得合作 API 前必须如实标记免费预览或会员限制，不得绕过。不得调用系统默认浏览器。
5. 展示来源、公司、职位、地点、岗位链接、申请链接、匹配点、缺口和风险。当前打开页面只算环境上下文，绝不等于用户选择。
6. 用户明确选择单个岗位后，说明目标网站、会填写的数据类别和提交模式，再运行 `scripts/confirmation_gate.py select`，把公司、职位、岗位链接、申请链接、选择时间和模式写入 `.fanhan-job-agent/selected-external-job.json`。默认 `--submission-mode auto`；用户明确说“我自己提交”时使用 `manual`。记录缺失或与当前岗位不一致时，禁止发送个人数据、上传材料或准备提交。
7. 返回 `$fanhan-job-agent` 执行“选岗后的统一定制流程”：展示匹配点、缺口、风险和具体修改建议；第一份候选人可见成稿必须是与当前公司和职位绑定的完整可编辑 HTML，并立即在 Codex 侧边栏展示。用户检查、修改、亲自导出并回传同名 PDF，经 `material_gate.py --accept-exported-pdf` 原文件接收后才能继续；不得从磁盘 HTML 或其他脚本重新生成 PDF，缺少任一产物时不得打开申请表。
8. 使用 EgoLite 复用当前岗位的同一 TaskSpace。登录、扫码、验证码、浏览器权限提示和风控由用户接管。必须先从顶部到底部读取完整表单，盘点所有文字、单选、多选、下拉、文件、协议和最终动作；不能只处理当前可见区域。先找学历、经验年限、工作许可、到岗时间和薪资等淘汰题，用当前职业档案预检；明确冲突、敏感字段或未知项都先让候选人决定，不能替候选人选择虚假答案。输入个人信息或上传文件前运行 `confirmation_gate.py build`，并用 `--field-name` 逐项传入全部字段；失败时不得绕过。
9. 开放题返回 `$fanhan-job-agent` 查询本地申请回答库。可用已确认职业事实针对当前 JD 自动改写；需要新增事实、涉及敏感选择或与档案冲突时暂停询问。能可靠填写的字段尽量填写，每次填写后重新读取页面实际值；被清空、无法读取或无法验证的字段都按未完成处理。只要仍有人工步骤，就一次性给出覆盖全部字段的清单，必填项在前。
10. 展示即将提交的公司、岗位、网站、简历文件、字段清单和最终按钮，用与 `build` 完全相同的参数运行 `confirmation_gate.py verify --expected '<fingerprint>'`。选岗、页面、材料、字段或最终动作变化时停止。模式为 `auto` 时验证通过后只点击一次最终按钮；模式为 `manual` 时把同一 EgoLite TaskSpace 交给用户本人点击。
11. 最终提交动作发生后，只凭明确成功文案、申请编号或平台状态记录 `success`；明确失败记为 `failed`；结果含糊或超时记为 `failed: submission_outcome_unknown`，不得自动重试。用户决定不提交时记录 `user_declined`。写入任一终态后立即返回 `$fanhan-job-agent` 执行“统一进入泛函业务”；不得直接启动面试辅助。
12. 任何来源或申请页出现新的失败、恢复或行为变化后，返回 `$fanhan-job-agent` 按本地双记忆契约更新 `Agent平台执行记忆.md`；只记录平台技术事实，不记录候选人资料和登录凭据。

## 外部来源读取规则

1. Bonjour 从公开职位页随页面返回的岗位数据读取；不要先打开右侧栏逐卡滚动。脚本没有识别到岗位时标记 `暂不可用`，不得写成 `无结果`。
2. Watcha 从查岗页自己使用的公开接口 `https://watcha.cn/jobs-api/v1/public/teams` 读取。`/study/jobs` 是 SPA 路由，初始标题或营销文案不能作为“没有岗位”的证据。
3. JobRadar 默认返回 `membership_required`：免费层只提供基础预览，完整岗位与投递入口需登录/会员。未获得合作 API 前不得直接读取其后台数据库绕过限制。
4. 右侧栏浏览器只在用户选中岗位后用于查看详情、登录和申请。公开数据读取失败时保留结构化失败状态并继续其他来源，不用浏览器反复重试搜索。

## 硬边界

- 不绕过验证码，不保存密码、Cookie、Token 或登录态。
- 日志不保存简历正文、作品集正文、表单答案、证件信息或联系方式；完整手工填写清单只在当前候选人对话中展示。
- 原始简历和仅做格式转换的 PDF 不得上传；文件名未绑定当前候选人、公司和职位时不得进入申请页。
- 只有 PDF、没有同名可编辑 HTML，或 PDF 生成时间早于 HTML 时不得进入申请页。
- 只投用户明确选中的岗位；搜索结果、推荐结果和打开的页面都不构成投递授权。
- 不启动独立 Chrome 或 Playwright；申请页只使用当前 `$ego-browser` TaskSpace/Page API。
- 默认自动提交只在岗位专属简历已经预览、回传并通过材料门禁后生效；用户明确要求本人提交时必须交接。
- 不因用户曾说“都投”或“继续”而跳过当前岗位确认。
- 只有 Bonjour、Watcha 和 JobRadar 提供结构化读取；来源快照中的其他网站只做经过确认的定向探索，不承诺稳定适配。
- 当前版本不支持 WorkBuddy 外部投递、云端账号/数据库、积分付费或自动批量代投。

## 常用命令

```bash
python3 scripts/confirmation_gate.py select --company '<公司>' --job-title '<职位>' --job-url '<岗位链接>' --application-url '<申请链接>' --submission-mode auto --output .fanhan-job-agent/selected-external-job.json --confirmed
python3 scripts/source_catalog.py --query '<目标岗位 地点 办公方式>' --limit 5
python3 scripts/external_jobs.py --query '<求职关键词>' --limit 20
python3 scripts/watcha_jobs.py --query '<求职关键词>' --limit 20
python3 scripts/source_feedback.py prepare --name '<网站名称>' --url '<网站 URL>' --intro '<一句话简介>'
python3 scripts/source_feedback.py send --state .fanhan-job-agent/source-suggestion.json --confirmed
python3 scripts/application_log.py duplicate --job-url '<岗位链接>' --application-url '<申请链接>'
python3 scripts/confirmation_gate.py build --company '<公司>' --job-title '<职位>' --job-url '<岗位链接>' --application-url '<申请链接>' --profile .fanhan-job-agent/profile.json --profile-status .fanhan-job-agent/profile-status.json --career-document .fanhan-job-agent/职业经历.md --proposal .fanhan-job-agent/tailored-proposal.json --resume '.fanhan-job-agent/outbox/<姓名-目标公司-目标岗位-日期-vN.pdf>' --field-name email --field-name phone --final-action '<按钮文字>' --selection .fanhan-job-agent/selected-external-job.json
python3 scripts/confirmation_gate.py verify --company '<公司>' --job-title '<职位>' --job-url '<岗位链接>' --application-url '<申请链接>' --profile .fanhan-job-agent/profile.json --profile-status .fanhan-job-agent/profile-status.json --career-document .fanhan-job-agent/职业经历.md --proposal .fanhan-job-agent/tailored-proposal.json --resume '.fanhan-job-agent/outbox/<姓名-目标公司-目标岗位-日期-vN.pdf>' --field-name email --field-name phone --final-action '<按钮文字>' --selection .fanhan-job-agent/selected-external-job.json --expected '<build 返回的 fingerprint>'
python3 scripts/application_log.py append --source '<Bonjour|Watcha|JobRadar>' --company '<公司>' --job-title '<职位>' --job-url '<岗位链接>' --application-url '<申请链接>' --status user_declined --user-confirmed false --reason user_declined
```
