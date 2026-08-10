# TalentOS HR Agent

TalentOS is a Streamlit-based HR intelligence platform for JD generation, resume screening, talent sourcing, and feedback-driven Skill optimization.

The product principle is human-in-the-loop: AI can generate, parse, score, search, summarize, and suggest improvements, but all recruiting decisions and rule changes require explicit human confirmation.

## Current Features

### 1. JD Generation

- Generate a structured JD from simple hiring inputs.
- Infer job fields from short natural-language descriptions.
- Produce candidate-facing JD text, internal job profile, screening strategy, and interview focus.
- Confirmed JDs enter the job library and can be reused by resume screening and talent sourcing.
- JD drafts and confirmed job profiles are persisted locally.

### 2. Resume Screening

- Select a confirmed JD from the job library.
- Upload resumes and parse candidate profiles.
- Run evidence-based person-job matching.
- Apply social-hiring or campus-hiring Matching Skill rules.
- HR manually marks candidates as recommended, pending, or not recommended.
- Candidate decisions enter the feedback tracking workflow.

### 3. Talent Sourcing

- Create a sourcing task manually or from an existing confirmed JD.
- Generate sourcing strategy, keywords, search queries, risk notes, and data-source priorities.
- Search public sources including GitHub and arXiv.
- Optional Google Scholar providers are supported through third-party APIs.
- Company People API integration is reserved but disabled until configured.
- External candidates can be reviewed one at a time, with evidence links and authenticity status.
- Candidates enter the talent pool only after manual confirmation.

### 4. Feedback Tracking

- Track follow-up results for screened candidates.
- Collect final interview or business-screening feedback.
- Classify valid optimization samples.
- Summarize feedback tags, misjudgment types, and Skill-level sample statistics.
- Generate optimization suggestions after enough valid feedback samples.
- Suggestions are draft-only; Skill files are not modified without human confirmation.

### 5. Workflow / Matching Management

The management page separates two kinds of Skill:

- Workflow Skill: model call flow, prompt purpose, output schema, and safety boundaries.
- Matching Skill: scoring dimensions, weights, evidence rules, positive signals, negative signals, and interview focus.

Current Workflow Skills:

- `skills/workflows/jd_generation_workflow.md`
- `skills/workflows/resume_screening_workflow.md`
- `skills/workflows/talent_sourcing_workflow.md`
- `skills/workflows/feedback_optimization_workflow.md`

Current Matching Skills:

- `skills/matching/dev_social_v1.md`
- `skills/matching/dev_campus_v1.md`

## Architecture

```text
app.py
├── modules/
│   ├── jd_generation/
│   │   ├── jd_generator.py
│   │   └── jd_parser.py
│   ├── resume_screening/
│   │   ├── profile_parser.py
│   │   ├── scoring_engine.py
│   │   ├── ranker.py
│   │   ├── report_gen.py
│   │   └── interview_gen.py
│   ├── talent_pool/
│   │   ├── sourcing.py
│   │   ├── talent_pool.py
│   │   └── people_system.py
│   └── analytics/
├── skills/
│   ├── workflows/
│   └── matching/
├── utils/
│   ├── db.py
│   ├── file_loader.py
│   ├── llm_client.py
│   └── security.py
└── models/
    └── schemas.py
```

SQLite is used for local persistence. Runtime data is stored under `data/`, which is intentionally ignored by Git.

## LLM Providers

The platform supports provider selection through environment variables and the Streamlit sidebar.

Supported providers:

- MiniMax through Anthropic-compatible SDK endpoint.
- Groq through the Groq SDK.

Main configuration lives in `.env.example`. Copy it to `.env` and fill in local secrets.

```bash
cp .env.example .env
```

Important variables:

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

Do not commit `.env`. It is ignored by `.gitignore`.

## People API Integration

The internal talent pool is not simulated with local demo data.

People API features are enabled only when `PEOPLE_API_BASE_URL` is configured. Until then:

- Internal People API search returns no records.
- The UI displays the People API as not connected.
- Local SQLite talent records are treated only as external manually confirmed candidates.

See:

```text
docs/people_system_api_contract.md
```

## Setup

```bash
git clone <repo_url>
cd talentos-hr-agent

python3 -m venv venv
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and add the API keys you want to use.

## Run

```bash
source venv/bin/activate
streamlit run app.py
```

Or explicitly:

```bash
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

Open:

```text
http://127.0.0.1:8501
```

## Recommended Workflow

1. Open `JD 生成`.
2. Enter basic hiring need and generate a JD.
3. Review and manually confirm the JD into the job library.
4. Open `简历筛选`.
5. Select the confirmed JD and upload resumes.
6. Review AI matching results and manually mark candidate tiers.
7. Complete feedback later in `反馈追踪`.
8. After enough valid feedback samples, review Skill optimization suggestions.

For sourcing:

1. Open `人才开源`.
2. Create a sourcing task manually or from a confirmed JD.
3. Confirm sourcing strategy.
4. Generate candidate leads from public sources.
5. Review one candidate at a time.
6. Manually mark focus, reject, or add to external talent pool.

## Security And Data Handling

Ignored by Git:

- `.env`
- `data/`
- `*.db`
- `*.bak`
- `*.log`
- `venv/`
- generated local runtime files

Before pushing, verify:

```bash
git status --short --ignored
git ls-tree -r --name-only HEAD | rg '(^\.env$|^data/|\.db$|\.bak$|hr_agent\.log|^venv/)'
```

The second command should return no tracked sensitive runtime files.

## Current Repository Notes

- The Streamlit theme is configured for a light beige and mint-green SaaS style.
- Workflow and Matching Skills are Markdown-backed and intended for HR review.
- AI suggestions never automatically modify Matching Skill files.
- The current GitHub repository is private by default.

