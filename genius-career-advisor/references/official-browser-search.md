# 官网浏览器读取

`external_jobs.py` 先并行读取公开职位数据，再对仍未读到列表的相关官网运行无头浏览器。默认补读 5 家，可用 `--browser-limit` 调整。浏览器阶段最多同时运行两家，每家预算 45 秒，最多读取四页。读取后再按本轮查询筛选，避免前一页的工程岗位挤掉后一页的产品岗位。

## 首次准备

使用运行 Skill 的同一 Python 环境安装 Playwright。可优先使用该项目的虚拟环境。

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

运行时优先使用 Playwright 的 Chromium，缺失时尝试本机 Chrome。依赖或浏览器缺失会在对应来源的 `error` 中返回 `browser_dependency_missing` 或 `browser_runtime_missing`。操作者据此准备环境后重试。原有公开来源继续返回岗位。

## 结果核对

- 浏览器沿官网公开的招聘链接进入实际职位列表。Moka 的 `#/job/...` 是职位标识，去重时保留。
- 岗位名采用实际卡片标题，包括 AI Search Builder、Agent Harness 团队等名称。地点缺失时保持未知。
- 查询在页面读取之后执行，结果使用同一份职业档案合并、去重和排序。
- 时间或页数预算耗尽时保留已经读取的岗位。读取页数受预算限制，列表显示的总数不能作为已获取数量。
- 登录、验证码和访问限制按真实失败记录。会员来源按现有过滤规则处理。
