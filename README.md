# 天才职业顾问 @ 泛函

让 Agent 先了解候选人的真实经历，再帮助建立职业档案、寻找岗位、生成岗位专用简历并辅助申请。

本仓库已经包含完整运行所需的四个 Skill。新用户不需要再单独安装「职业资产」。

## 一条链接安装

把下面这句话发给支持 Agent Skills 的 Agent：

```text
请把这个 GitHub 仓库中的全部 Skill 安装到当前 Agent：
https://github.com/Ivor-NCUT/genius-career-advisor-skill
```

Codex 也可以直接运行：

```bash
npx skills add https://github.com/Ivor-NCUT/genius-career-advisor-skill \
  --skill '*' -g -a codex -y
```

安装完成后，面向用户只需要使用「天才职业顾问」入口：

```text
使用 $fanhan-job-agent 帮我找适合的工作，这是我的简历。先建立职业档案并找岗，暂时不要投递。
```

## 包含的 Skill

| Skill | 作用 |
| --- | --- |
| `fanhan-job-agent` | 唯一面向用户的产品入口，显示名称为「天才职业顾问」 |
| `职业资产` | 阅读材料、深挖经历并维护长期职业主档 |
| `apply-external-jobs` | 从已核对的岗位来源中选取渠道并辅助外部申请 |
| `apply-jobradar` | 兼容旧版 Prompt，并转交给当前主流程 |

普通用户不需要分别调用后三个 Skill，主入口会按流程自动调用。

## 核心流程

1. 读取 PDF 或 DOCX 简历，建立可长期复用的职业档案。
2. 根据候选人的方向和限制，从泛函与已核对的岗位来源统一找岗。
3. 用户选定岗位后，分析匹配点、缺口与风险，并追问最值得补充的事实。
4. 生成可编辑的岗位专用 HTML 简历，由用户检查并导出 PDF。
5. Agent 辅助整理申请表；登录、验证码、文件上传和最终提交由用户确认。
6. 候选人明确授权后，才把资料交给泛函用于岗位匹配和人工审核。

## 安全边界

- 原始材料默认只在用户当前环境处理。
- 未经明确授权，不向泛函或招聘网站上传个人资料。
- 不编造候选人经历、数据或岗位结果。
- 最终投递由候选人本人检查和确认。
- 当前版本是辅助投递，不承诺无人值守自动代投。

## 仓库结构

```text
genius-career-advisor-skill/
├── fanhan-job-agent/       # 天才职业顾问主入口
├── career-assets/          # 职业资产
├── apply-external-jobs/    # 外部岗位与申请辅助
├── apply-jobradar/         # 旧 Prompt 兼容入口
└── docs/                   # 技术探测与接入说明
```

## 验证安装内容

只查看仓库能发现哪些 Skill，不执行安装：

```bash
npx skills add https://github.com/Ivor-NCUT/genius-career-advisor-skill --list
```

---

候选人免费使用 Skill；泛函通过招聘服务与企业合作。
