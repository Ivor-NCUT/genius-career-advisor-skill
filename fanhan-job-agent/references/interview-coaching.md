# 轻量面试辅导

这是一条完成泛函业务入库后的可选流程，不阻塞找岗、简历生成或投递。候选人主动要求面试辅导，或明确确认已经进入真实面试阶段时启用；不能因投递结束、放弃投递、飞书通知成功或用户说“继续测试”而自动启动。

## 故事库

先从 `职业经历.md` 选择与目标 JD 最相关的真实经历，整理为情境、任务、行动、结果。候选人确认后写入本地故事库：

```bash
python3 <skill-root>/scripts/candidate_memory.py add-story \
  --title '<故事名>' \
  --situation '<背景>' \
  --task '<任务>' \
  --action '<候选人本人采取的行动>' \
  --result '<可验证结果>' \
  --evidence '<职业经历.md 中的位置>' \
  --question-type '<适用问题>' \
  --confirmed
```

不能把团队成果自动写成候选人的个人贡献，也不能为完整 STAR 结构补造结果。

## 模拟面试

1. 根据当前 JD、候选人缺口和故事库选择一个最高价值问题。
2. 一次只问一个，等待候选人回答；证据模糊时最多追问两次。
3. 先复述听到的事实，再反馈，不直接替候选人编答案。
4. 按 1–5 分评估：内容证据、表达结构、岗位相关性、可信度、个人差异性。
5. 只给一个最优先改进动作，并生成一版基于真实事实的参考表达。
6. 候选人看过反馈后，把本轮摘要写入 `candidate-memory.json`：

```bash
python3 <skill-root>/scripts/candidate_memory.py record-practice \
  --company '<公司>' --job-title '<岗位>' \
  --question '<问题>' --answer-summary '<回答摘要>' \
  --substance 1 --structure 1 --relevance 1 --credibility 1 --differentiation 1 \
  --what-worked '<最有效的一点>' --priority-move '<下一次只改这一点>'
```

## 复盘

真实面试结束后，先记录被问问题、候选人实际回答、面试官追问和候选人自己的判断。没有逐字稿也可以复盘；不得把候选人的感觉写成面试官结论。对比历史练习只描述趋势，不把练习分数解释为录取概率。

完整的录音转写、多轮评分校准、薪资谈判和 Offer 对比仍属于后续版本；当前版本只保留故事库、单题模拟和复盘记录。
