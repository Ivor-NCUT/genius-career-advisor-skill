# 申请回答库

文件位置：当前工作区 `.fanhan-job-agent/candidate-memory.json`。它只保存在本地，不进入 `external-applications.jsonl`、Git、泛函工作台或招聘网站。

## 使用时机

读取申请表后，先把问题归为：经历、动机、行为、工作方法、工具、求职条件或其他。对每个需要自由文本回答的问题运行：

```bash
python3 <skill-root>/scripts/candidate_memory.py find-answer --question '<当前问题>'
```

命中历史答案时，先展示原问题、答案、公司和岗位，再让候选人选择：

1. 沿用；
2. 针对当前 JD 改写；
3. 重新回答。

不能因为文字相似就直接填入旧答案。“为什么加入公司”等动机问题默认需要针对当前公司改写；工作许可、薪资、到岗时间等条件问题必须以当前职业档案为准。

生成答案时只回答字段真正询问的内容：单行字段通常一句，短回答 2–4 句，长文本默认 100–200 字；经历题给事实和证据，动机题必须连接当前公司与候选人的真实经历，行为题使用压缩后的 STAR。不要重复整段 JD，也不要把求职信塞进一个表单框。

## 写入规则

只有候选人看过并明确确认的最终答案才能写入：

```bash
python3 <skill-root>/scripts/candidate_memory.py add-answer \
  --question '<表单原问题>' \
  --question-type '<experience|motivation|behavioral|process|tools|logistics|other>' \
  --answer '<候选人确认的答案>' \
  --company '<公司>' \
  --job-title '<岗位>' \
  --evidence '<职业经历.md 或候选人明确回答的位置>' \
  --confirmed
```

- 不得用模型推断充当证据。
- 新增事实先写回 `$职业资产` 的长期主档，再保存答案。
- 相同公司、岗位和问题再次确认时更新原记录，不制造重复版本。
- 回答库可以包含申请答案正文，因此权限固定为仅当前用户可读写；不得复制到非本地投递日志。
