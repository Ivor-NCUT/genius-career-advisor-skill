# WorkBuddy 安装与启动烟测

WorkBuddy 当前支持导入本地 Skill 压缩包。参考：[腾讯云 WorkBuddy 技能说明](https://cloud.tencent.com/document/product/1831/134432) 与 [WorkBuddy Skill 加载教程](https://workbuddy.homes/bluebook/%E7%AC%AC%E4%B8%80%E7%AF%87%20%E4%BD%BF%E7%94%A8%E6%89%8B%E5%86%8C%EF%BC%9A%E5%85%88%E6%8A%8A%20WorkBuddy%20%E7%94%A8%E8%B5%B7%E6%9D%A5/%E7%AC%AC%205%20%E7%AB%A0%20WorkBuddy%E5%8A%A0%E8%BD%BD%E4%B8%80%E4%B8%AA%E7%9C%9F%E6%AD%A3%E7%94%A8%E5%BE%97%E4%B8%8A%E7%9A%84%20Skill/)。

## 安装

1. 将 `fanhan-job-agent/` 目录压缩为 zip，压缩包根目录必须直接包含 `SKILL.md`、`agents/` 和 `references/`。
2. 在 WorkBuddy 左侧进入“专家·技能·连接器”，选择“上传技能”，导入该 zip。
3. 在“我安装的”确认“天才职业顾问”已启用；如未出现，重启 WorkBuddy 后再查。

## 启动验收

新建会话，通过 `/` 选择该 Skill，输入：

```text
我想整理求职材料，但现在还不授权上传。请告诉我需要提供什么。
```

通过条件：

- 明确说明材料默认本地处理、授权前不上传。
- 只要求原始简历，说明作品集、GitHub 和个人网站可选。
- 不要求平台账号、积分或付费。
- 不调用工作台文件上传或候选人申请接口。

本烟测只证明 Skill 能安装、触发并进入材料采集，不证明 WorkBuddy 已完成浏览器投递或工作台全链路。
