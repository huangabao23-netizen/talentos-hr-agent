# TalentOS HR Agent

[中文版](./README.md)

TalentOS HR Agent is a Streamlit-based HR intelligence platform for JD generation, resume screening, talent sourcing, and feedback-driven Skill optimization.

The system follows a human-in-the-loop principle: AI generates, parses, searches, scores, and summarizes; humans confirm job profiles, candidate tiers, talent-pool entry, feedback records, and Skill changes.

## Main Features

### JD Generation

- Generate JD drafts from simple hiring requirements.
- Produce job profiles, screening strategies, and interview focus areas.
- Confirmed JDs enter the job library.
- Confirmed jobs can be reused by resume screening and talent sourcing.

### Resume Screening

- Select a confirmed JD from the job library.
- Upload resumes and parse candidate profiles.
- Run person-job matching with social-hiring or campus-hiring Matching Skills.
- Manually mark candidates as recommended, pending, or not recommended.
- Screening decisions enter feedback tracking.

### Talent Sourcing

- Create sourcing tasks manually or from confirmed JDs.
- Generate sourcing strategies, keywords, search queries, and risk notes.
- Search public sources such as GitHub and arXiv.
- Reserve integration points for a company People API.
- Candidate leads must be manually reviewed before entering the talent pool.

### Feedback Tracking

- Track business screening, interviews, and final candidate outcomes.
- Accumulate valid feedback samples.
- Generate Skill optimization suggestion drafts.
- Suggestions do not modify Skill files until manually confirmed.

### Workflow / Matching Management

- Workflow Skill: model call flow, prompts, output schemas, and boundaries.
- Matching Skill: scoring dimensions, weights, evidence rules, positive and negative signals, and interview focus.

## Project Structure

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

## Core Directories

```text
modules/jd_generation/
```

JD field inference, JD generation, and JD parsing.

```text
modules/resume_screening/
```

Resume parsing, person-job matching, ranking, reports, and interview question generation.

```text
modules/talent_pool/
```

Talent sourcing, lead review, external talent pool, and People API adapter.

```text
skills/workflows/
```

Business Workflow Skills for JD generation, resume screening, talent sourcing, and feedback optimization.

```text
skills/matching/
```

Social-hiring and campus-hiring Matching Skills maintained as Markdown scoring rules.

## Run Locally

### 1. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Then fill in the model or data-source configuration you need.

Common configuration:

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

### 4. Start the app

```bash
streamlit run app.py
```

Or:

```bash
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open:

```text
http://127.0.0.1:8501
```

