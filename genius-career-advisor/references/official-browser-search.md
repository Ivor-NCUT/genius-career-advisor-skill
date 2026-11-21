# 官网浏览器读取

`external_jobs.py` 先并行读取公开职位数据，再对仍未读到列表的相关官网运行无头浏览器。默认补读 5 家，可用 `--browser-limit` 调整。浏览器阶段最多同时运行两家，每家预算 45 秒，最多读取四页。读取后再按本轮查询筛选，避免前一页的工程岗位挤掉后一页的产品岗位。

## 首次准备

使用运行 Skill 的同一 Python 环境安装 Playwright。可优先使用该项目的虚拟环境。

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

运行时优先使用 Playwright 的 Chromium，缺失时尝试本机 Chrome。依赖或浏览器缺失会在对应来源的 `error` 中返回 `browser_dependency_missing` 或 `browser_runtime_missing`。操作者据此准备环境后重试。原有公开来源继续返回岗位。

## 复用与名额

读到的官网职位写在 `data/career-read-cache.json`，带读取时间。开始找岗时，24 小时内已经读到的官网职位直接按本次查询匹配，不再重新打开这些官网，也不占浏览器名额。名额先给用户点名的公司，再给最久没检查的官网。没轮到浏览器的来源是 `not_browser_checked`（尚未验证）。读到职位但不符合本次查询是 `collected_no_match`，不算来源失败。

失败原因分开记录：`not_browser_checked`、`page_not_ready`、`parser_gap`、`dead_url`、`network_error`、`login_or_restricted`、`no_public_jobs`。

完整排查用 `python3 scripts/coverage_report.py`。它会先走 HTTP，再对尚未读通的官网逐家打开浏览器。日常搜索仍受 `--browser-limit` 限制。

## 结果核对

- 浏览器沿官网公开的招聘链接进入实际职位列表。Moka 的 `#/job/...` 是职位标识，去重时保留。
- 岗位名采用实际卡片标题，包括 AI Search Builder、Agent Harness 团队等名称。地点缺失时保持未知。
- 查询在页面读取之后执行，结果使用同一份职业档案合并、去重和排序。
- 时间或页数预算耗尽时保留已经读取的岗位。读取页数受预算限制，列表显示的总数不能作为已获取数量。
- 登录、验证码和访问限制按真实失败记录。会员来源按现有过滤规则处理。
