# 第三方求职 Skill 借鉴记录

首次审查：2026-08-18。`ai-job-search` 深度整合更新：2026-09-02，对应 Issue #4。

求职工作流部分只借鉴公开设计，未复制第三方 Skill 代码、提示词正文、品牌名称或浏览器程序。

| 来源 | 许可证 | 借鉴点 | 本仓库实现 |
|---|---|---|---|
| [santifer/career-ops](https://github.com/santifer/career-ops) | MIT | 投递前淘汰题预检、最终提交由用户完成 | 复用现有 `match_guard.py`、选岗门禁和侧边栏辅助流程；不接入其 Chrome/Playwright 实现 |
| [noamseg/interview-coach-skill](https://github.com/noamseg/interview-coach-skill) | MIT | 可复用申请回答、故事库、一次一问、五维反馈和复盘 | 新增本地 `candidate-memory.json`、申请回答库与轻量面试流程 |
| [MadsLorentzen/ai-job-search](https://github.com/MadsLorentzen/ai-job-search) | MIT | 快速初筛与选岗后深评分层、公司事实核验、按需求职信、申请结果复盘 | 复用现有来源、职业档案、回答库和投递日志，新增 `job-evaluation-and-outcomes.md` 与结果事件；不复制丹麦站点爬虫、个人模板或 Claude 专用命令 |
| [Paramchoudhary/ResumeSkills](https://github.com/Paramchoudhary/ResumeSkills) | MIT | 表单答案按问题类型生成 | 复用现有职业资产和 JD 定制流程，只补回答复用，不安装其 20 个独立 Skill |
| [GresonKwan/JobOK](https://github.com/GresonKwan/JobOK) | MIT | 中文求职边界、用户手动确认外部动作 | 现有确认门禁已经覆盖，不复制重复流程 |

## 页面内 PDF 运行依赖

- `html2pdf.js` 0.14.0：MIT；把候选人在本地 HTML 中修改后的当前页面转换为 PDF。
- 使用官方已修复 2026 年 XSS 公告的 0.14.0 版本；依赖包和完整许可证保存在 `fanhan-job-agent/assets/`。
- 转换完全在候选人本地页面内进行，不向第三方上传简历内容，也不在运行时访问 CDN。

## 明确排除

- 不自动点击最终提交。
- 不启动独立 Chrome、Playwright 或 CDP 会话。
- 不扩大到更多招聘平台或批量抓取。
- 不把申请答案、面试记录或候选人材料写入 Git、外部投递日志或工作台。
