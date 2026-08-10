---
skill_id: feedback_optimization_workflow_skill
skill_name: 反馈调优 Workflow Skill
module: 反馈追踪
version: v1
prompt_count: 1
owner: HR
editable: false
requires_hr_confirmation: true
status: active
---

# 反馈调优 Workflow Skill

## 使用场景

用于 `反馈追踪` 管理页。它基于匿名化候选人反馈样本分析误判规律，并生成可供 HR 审核的 Skill 优化建议。

## 调用链路

1. 收集候选人后续反馈。
2. 判断是否为有效调优样本。
3. 满足约 20 条有效样本后，基于匿名化样本生成优化建议。
4. 用户人工审核建议。
5. 后续才可以生成新版本 Matching Skill 或 Workflow Skill。

## 与 Matching Skill 的关系

- 本 Workflow 只产出调优建议。
- 需要调整评分权重、硬性检查、正负向信号时，目标文件是 `skills/matching/*.md`。
- 需要调整调用链路或输出结构时，目标文件是 `skills/workflows/*.md`。
- 两类修改都必须由用户确认后再生效。

## Prompt: Skill 优化建议

### 触发位置

`app.py::_build_skill_optimization_prompt`

### System Prompt

```text
你只输出可解析 JSON。
```

### User Prompt 模板

```text
你是一名招聘评估体系优化专家，你的任务是基于匿名化招聘反馈样本，分析当前匹配 Skill 的误判规律，并生成可供 HR 审核的优化建议。

当前 Skill：
{skill}

匿名化反馈样本：
{anonymized_samples}

请只返回 JSON，不要返回 Markdown。JSON 字段：
{
  "sample_summary": {
    "total_samples": 0,
    "positive_samples": 0,
    "negative_samples": 0,
    "main_misjudgments": ["..."]
  },
  "misjudgment_patterns": [
    {"pattern": "...", "evidence": "...", "severity": "高/中/低"}
  ],
  "weight_adjustment_suggestions": [
    {"dimension": "...", "current_issue": "...", "suggestion": "..."}
  ],
  "rule_change_suggestions": [
    {"section": "正向信号/负向信号/证据规则/面试关注点", "action": "新增/修改/删除", "content": "...", "reason": "..."}
  ],
  "risk_controls": ["..."],
  "requires_hr_confirmation": true
}

要求：
- 只能生成建议，不要声称已修改 Skill。
- 不要输出候选人真实姓名。
- 如果样本量不足或信号弱，要明确提示不建议自动调权。
```

## 样本有效性规则

有效调优样本必须同时满足：

- 候选人记录状态为 `已反馈`。
- 有明确后续结果。
- 有原因、备注或业务反馈。

## 人工确认原则

- AI 只生成调优建议，不自动修改 Skill。
- 用户确认前，不覆盖 `skills/matching/*.md`。
- 后续若启用新版本，应生成新文件，例如 `dev_social_v2.md` 或 `dev_campus_v2.md`。
