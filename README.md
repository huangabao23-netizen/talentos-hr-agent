# TalentOS HR Agent

[English Version](./README_EN.md)

TalentOS HR Agent 是一个基于 Streamlit 的招聘智能体平台，用于支持 JD 生成、简历筛选、人才开源和反馈驱动的 Skill 优化。

系统遵循 human-in-the-loop 原则：AI 负责生成、解析、检索、评分和总结，岗位确认、候选人分层、人才入库、反馈记录和 Skill 修改都需要人工确认。

## 主要功能

### JD 生成

- 根据简单岗位需求生成 JD 草稿。
- 自动整理岗位画像、筛选策略和面试关注点。
- 用户确认后进入岗位库。
- 已确认岗位可被简历筛选和人才开源复用。

### 简历筛选

- 从岗位库选择已确认 JD。
- 上传简历并解析候选人画像。
- 基于社招或校招 Matching Skill 做人岗匹配。
- 用户手动标记推荐、待定或不推荐。
- 筛选结果进入反馈追踪。

### 人才开源

- 支持手动创建寻访任务，或从已确认 JD 创建。
- 生成寻访策略、关键词、搜索 query 和风险提示。
- 支持 GitHub、arXiv 等公开来源。
- 预留公司 People API 接入。
- 候选线索需要人工核验后才可入库。

### 反馈追踪

- 记录候选人的后续业务筛选、面试和最终结果。
- 累积有效反馈样本。
- 生成 Skill 优化建议草案。
- 优化建议不会自动写入 Skill，需要人工确认。

### Workflow / Matching 管理

- Workflow Skill：管理模型调用链路、Prompt、输出结构和边界。
- Matching Skill：管理评分维度、权重、证据规则、正负向信号和面试关注点。

## 项目结构

```text
talentos-hr-agent/
├── app.py
├── modules/
│   ├── jd_generation/
│   ├── resume_screening/
│   ├── talent_pool/
│   └── analytics/
├── skills/
│   ├── workflows/
│   └── matching/
├── utils/
│   ├── db.py
│   ├── file_loader.py
│   ├── llm_client.py
│   └── security.py
├── models/
│   └── schemas.py
├── docs/
│   └── people_system_api_contract.md
├── requirements.txt
├── .env.example
└── README.md
```

## 核心目录说明

```text
modules/jd_generation/
```

JD 字段识别、JD 生成和 JD 解析。

```text
modules/resume_screening/
```

简历解析、人岗匹配评分、排序、报告和面试题生成。

```text
modules/talent_pool/
```

人才开源、候选线索核验、外部人才库和 People API 适配。

```text
skills/workflows/
```

业务 Workflow Skill，包括 JD 生成、简历筛选、人才开源和反馈调优。

```text
skills/matching/
```

社招和校招 Matching Skill，用 Markdown 维护评分规则。

## 运行方法

### 1. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

然后在 `.env` 中填写需要使用的模型或数据源配置。

常用配置：

```bash
LLM_PROVIDER=minimax
MINIMAX_API_KEY=
MINIMAX_MODEL=MiniMax-M3
ANTHROPIC_BASE_URL=https://api.minimaxi.com/anthropic

GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile

GITHUB_TOKEN=

PEOPLE_API_BASE_URL=
PEOPLE_API_TOKEN=
```

### 4. 启动应用

```bash
streamlit run app.py
```

或：

```bash
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

浏览器打开：

```text
http://127.0.0.1:8501
```

