# Matching Skill 维护说明

这个目录存放“人岗匹配评分 Skill”的自然语言配置。

程序会自动读取本目录下的 `*.md` 文件，除 `README.md` 外，每个 Markdown 文件代表一套评分 Skill。

当前已有：

- `dev_social_v1.md`：开发序列·社招评分 Skill
- `dev_campus_v1.md`：开发序列·校招评分 Skill

## 修改权重

直接修改对应 Markdown 文件里的 `## 评分权重` 表格。

权重建议总和保持为 `100%`。程序运行时会归一化权重，但为了人工审阅清晰，文档中应保持总和为 100%。

## 修改规则

可以直接修改以下章节：

- `## 硬性检查`
- `## 正向信号`
- `## 负向信号`
- `## 证据规则`
- `## 面试关注点`

这些内容会被传入简历匹配流程，用于评分解释、证据校准和面试关注点生成。

## 新增 Skill

复制一份现有 `.md` 文件，修改 front matter：

```markdown
---
skill_id: your_skill_id
skill_name: 你的评分 Skill 名称
job_family: 开发
hiring_type: 社招
version: v1
focus_summary: 这套 Skill 的评估重点。
---
```

然后调整评分权重和规则列表即可。
