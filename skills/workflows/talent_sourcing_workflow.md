---
skill_id: talent_sourcing_workflow_skill
skill_name: 人才开源 Workflow Skill
module: 人才开源
version: v1
prompt_count: 2
owner: HR
editable: false
requires_hr_confirmation: true
status: active
---

# 人才开源 Workflow Skill

## 使用场景

用于核心功能三 `人才开源`。它根据人才画像生成寻访策略，并从真实公开资料或未来授权 People API 中抽取候选线索、证据、风险和建议动作。

## 数据源原则

- 外部数据源只使用真实公开 API 或公开网页证据。
- 内部人才库只有配置公司 People API 后才可使用。
- 本地测试数据不能冒充公司人才库。
- 候选人入库、重点关注、暂不处理、联系动作都必须由用户人工确认。

## 与 Matching Skill 的关系

- 本 Workflow 负责生成寻访策略和候选线索。
- 候选线索进入评分阶段时，复用 `dev_social_v1` 或 `dev_campus_v1`。
- 高端人才寻访通常偏社招标准；校招、科研实习或应届线索才使用校招标准。
- 公开证据不足时，不应高估匹配度，应标记 `信息不足` 或 `需人工核验`。

## 调用链路

1. `人才开源策略 Prompt`：根据任务画像生成关键词、数据源优先级、搜索 Query 和风险提示。
2. `候选线索抽取 Prompt`：从公开资料中抽取候选人线索、证据链接和不确定性。

## Prompt: 人才开源策略

### 触发位置

`modules/talent_pool/sourcing.py::generate_sourcing_strategy`

### System Prompt

```text
你只输出可解析 JSON。
```

### User Prompt 模板

```text
你是高端技术人才寻访专家。请基于以下需求生成公开人才寻访策略。
只返回 JSON，不要返回 Markdown。

任务信息：
{task}

JSON 字段要求：
{
  "profile_summary": {
    "talent_direction": "...",
    "target_level": "...",
    "business_scene": "...",
    "focus_signals": ["..."],
    "exclusion_rules": "...",
    "location_preference": "..."
  },
  "core_keywords": ["..."],
  "expanded_keywords": ["..."],
  "source_priority": ["GitHub", "arXiv"],
  "search_queries": ["..."],
  "scoring_dimensions": [
    {"dimension": "方向匹配", "weight": "25%", "description": "..."}
  ],
  "risk_notes": ["..."]
}

要求：
- 搜索 query 默认围绕 GitHub、arXiv 生成；只有配置公司 People API 后才可使用公司人才库，Google Scholar 仅作为可选高级源。
- 不要建议绕过登录、验证码、权限墙。
- 强调候选人入库和联系必须人工确认。
```

## Prompt: 候选线索抽取

### 触发位置

`modules/talent_pool/sourcing.py::extract_candidate_leads`

### System Prompt

```text
你只输出可解析 JSON。
```

### User Prompt 模板

```text
你是高端技术人才寻访分析助手。请从公开资料中抽取可能匹配的人才线索。
只返回 JSON 数组，不要返回 Markdown。

寻访任务：
{task}

公开资料：
{public_material}

每个候选人 JSON 字段：
{
  "candidate_name": "姓名或待确认候选人",
  "current_org": "当前机构/公司/高校/未确认",
  "direction_tags": ["大模型", "Agent"],
  "match_score": 0-100,
  "recommendation_level": "高度匹配/可关注/信息不足",
  "recommendation_reason": "基于公开证据的推荐理由",
  "evidence_links": [
    {"title": "证据标题", "url": "https://...", "evidence_type": "论文/GitHub/主页/博客/演讲/新闻", "summary": "证据摘要"}
  ],
  "uncertainties": ["当前是否看机会未知"],
  "suggested_action": "加入人才库/重点关注/暂不处理"
}

规则：
- 只能基于公开资料下结论。
- 没有证据的字段写“未确认”。
- 推荐理由必须能被 evidence_links 或公开资料文本支撑。
- 不要输出私人电话、住址、身份证等敏感信息。
```

## 后续扩展位

- GitHub README 真实性分析 Prompt。
- 资料整理类仓库降权 Prompt。
- People API 候选人摘要 Prompt。
- 候选线索联系优先级 Prompt。

## 定向 Sourcing 触达话术

触达话术只生成草稿，不自动发送。使用前必须由用户确认候选人来源、公开证据、岗位匹配度和联系方式合规性。

### 高端社招候选人

话术目标：

- 强调岗位方向匹配
- 提及候选人的公开项目、论文或经历
- 不夸大、不冒充熟人、不透露敏感信息
- 邀请低压力沟通

模板：

```text
你好，我关注到你在 {公开项目/论文/技术方向} 上的经历，和我们目前在 {岗位方向/业务问题} 上寻找的人才方向比较接近。

这个岗位主要关注 {核心技术方向}，会涉及 {业务场景/技术挑战}，比较看重候选人在 {关键能力1}、{关键能力2}、{关键能力3} 方面的实际经验。

如果你近期愿意了解新的机会，我想和你简单交流一下岗位情况，也可以先把 JD 和团队方向发你参考。是否方便约一个 15 分钟的时间？
```

### 初阶高潜候选人

模板：

```text
你好，我看到你在 {项目/开源/竞赛/实习} 中有比较扎实的技术积累，尤其是 {具体亮点}，和我们当前 {岗位方向} 的初阶高潜人才画像比较接近。

这个岗位不只看年限，更关注基础能力、学习速度和真实项目贡献。你的经历里有一些点值得进一步了解，比如 {候选人亮点1}、{候选人亮点2}。

如果你愿意，我可以先发你岗位信息，你看是否有兴趣进一步沟通。
```

### 校招 / 实习候选人

模板：

```text
你好，我关注到你在 {学校/专业/项目/竞赛/科研/开源} 方面的经历，和我们目前 {校招/实习} 岗位方向比较匹配。

这个岗位主要面向 {方向}，会重点关注基础能力、项目贡献、学习能力和发展潜力。你在 {具体项目或经历} 中体现出的 {亮点}，和我们正在寻找的画像比较接近。

如果你对 {业务方向/技术方向} 感兴趣，我可以把岗位信息发你参考，也欢迎你简单介绍一下目前的实习/求职安排。
```

### 论文 / 开源候选人

模板：

```text
你好，我看到你在 {论文/开源项目名称} 中有相关工作，尤其是 {具体技术点/贡献点}，和我们正在做的 {业务方向/研究方向} 比较相关。

我们目前希望寻找在 {方向} 上有深入实践或研究经验的人选，岗位会涉及 {技术挑战/业务场景}。如果你愿意了解工业界相关机会，我可以先发你一些岗位和团队方向信息。

是否方便简单交流一下？
```

### 合规边界

- 不输出私人电话、住址、身份证等敏感信息。
- 不暗示系统已经确认候选人求职意愿。
- 不冒充熟人、校友、同事或业务方。
- 不自动发送，必须由用户人工确认后使用。
