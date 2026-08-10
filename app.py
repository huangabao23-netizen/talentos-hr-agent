"""
TalentOS — HR Intelligence Platform
Three modules:
  1) JD Generation and Job Profiles
  2) Resume Screening (existing pipeline, enhanced)
  3) Talent Sourcing / Resume Open Source
Light professional SaaS UI. Auto-writes config on startup.
"""

import os, sys, json, logging, tempfile, time, io, html, importlib
from pathlib import Path
from datetime import datetime

_cfg = Path(__file__).parent / ".streamlit" / "config.toml"
_cfg.parent.mkdir(exist_ok=True)
_cfg.write_text("""\
[theme]
base = "light"
primaryColor = "#69c987"
backgroundColor = "#fbf8ef"
secondaryBackgroundColor = "#fffdf7"
textColor = "#263426"
font = "sans serif"

[server]
headless = true
enableCORS = false

[browser]
gatherUsageStats = false
""")

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()

from modules.jd_generation.jd_parser import parse_jd
from modules.jd_generation.jd_generator import generate_jd_package, infer_jd_fields, summarize_table_records
from modules.resume_screening.profile_parser import parse_profile
from modules.resume_screening.scoring_engine import score_candidate
from modules.resume_screening.ranker import rank_candidates, apply_override
from modules.resume_screening.report_gen import generate_html_report, generate_json_export
from modules.resume_screening.interview_gen import generate_interview_questions, get_skills_gap
from skills.matching.matching_skills import (
    DIMENSION_KEYS,
    MATCHING_SKILLS,
    get_matching_skill,
    get_matching_skill_by_id,
)
from modules.talent_pool.talent_pool import (
    ingest_candidates, search_talents, get_skill_cloud,
    export_talent_pool_json, generate_open_resume_card,
)
from modules.talent_pool.sourcing import (
    confirm_sourcing_candidate_to_pool,
    generate_candidates_from_arxiv_api,
    generate_candidates_from_github_api,
    generate_candidates_from_google_scholar_api,
    generate_candidates_from_people_system,
    generate_sourcing_strategy,
    configured_google_scholar_provider_names,
    list_sourcing_candidates,
    list_sourcing_tasks,
    mark_sourcing_candidate,
    save_candidate_leads,
    score_sourcing_candidates,
    sourcing_stats,
)
from modules.talent_pool.people_system import people_system_enabled
from utils.file_loader import extract_text_from_file, extract_text_from_json
from utils.security import validate_file_extension
from utils.db import (
    init_db, seed_demo_data, talent_stats, get_db_path,
    add_candidate_followup, list_candidate_followups,
    update_candidate_followup, candidate_followup_stats,
    add_sourcing_task, get_sourcing_task, update_sourcing_task_strategy,
)
from utils.llm_client import (
    DEFAULT_GROQ_MODEL,
    DEFAULT_MINIMAX_MODEL,
    chat_completion,
    has_required_api_key,
    provider_label,
    required_key_name,
)
from models.schemas import CandidateResult, HireRecommendation, TalentPoolStatus, FunnelStage, GeneratedJD

init_db()

if os.environ.get("LANGCHAIN_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = "talentos-hr-agent"

BIASED_TERMS = ["ninja","rockstar","guru","wizard","hacker","aggressive",
    "dominant","young","energetic team","recent grad","digital native",
    "culture fit","native speaker","manpower","mankind"]

def check_jd_bias(text):
    return [t for t in BIASED_TERMS if t.lower() in text.lower()]

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("hr_agent.log"), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# ── PAGE CONFIG ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="TalentOS — HR Intelligence Platform",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── CSS ────────────────────────────────────────────────────────────────────────
_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

:root{
  --bg:#fbf8ef;
  --bg-2:#f4f0e4;
  --texture-dot:rgba(105,201,135,0.12);
  --texture-line:rgba(143,171,129,0.08);
  --surface:#fffdf7;
  --surface-glass:rgba(255,253,247,0.84);
  --surface-2:#f6fbf0;
  --border:#e8e2d2;
  --border-strong:#dbd3bf;
  --text:#263426;
  --text-soft:#40523f;
  --muted:#75806f;
  --muted-deep:#9a9f91;
  --primary:#69c987;
  --primary-hover:#4db66f;
  --primary-soft:#e9f8e8;
  --primary-2:#9bdc78;
  --primary-2-soft:#f0f8df;
  --cyan-line:#c8ebc8;
  --success:#4cae67;
  --warning:#c49a31;
  --purple:#8f7bd8;
  --blue:#5b9ad6;
  --glow:0 14px 36px rgba(83,139,82,0.10);
  --blue-glow:0 14px 36px rgba(76,124,94,0.08);
  --shadow:0 14px 32px rgba(75,70,48,0.08);
}

html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],.main,.main>div{
  background:
    radial-gradient(circle at 18% 10%,rgba(191,231,169,0.34),transparent 28%),
    radial-gradient(circle at 86% 8%,rgba(245,224,166,0.28),transparent 30%),
    linear-gradient(90deg,var(--texture-line) 1px,transparent 1px) 0 0/32px 32px,
    linear-gradient(0deg,var(--texture-line) 1px,transparent 1px) 0 0/32px 32px,
    linear-gradient(135deg,#fffdf6 0%,#fbf8ef 48%,#f3f8e9 100%)!important;
  color:var(--text)!important;
  font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif!important}
.main .block-container{padding:1.25rem 2rem 4rem!important;max-width:1480px!important}
*{font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif!important}

#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"],
[data-testid="stStatusWidget"],[data-testid="collapsedControl"],
button[kind="header"],div[data-testid="stSidebarCollapseButton"],
[data-testid="baseButton-headerNoPadding"]{display:none!important;visibility:hidden!important}
header[data-testid="stHeader"]{background:var(--bg)!important;height:0!important;min-height:0!important}

[data-testid="stSidebar"],[data-testid="stSidebar"]>div,
section[data-testid="stSidebar"]>div{
  background:rgba(250,248,239,0.88)!important;border-right:1px solid var(--border)!important;
  backdrop-filter:blur(18px)!important;box-shadow:10px 0 34px rgba(78,72,49,0.06)!important}
[data-testid="stSidebar"] *{color:var(--muted)!important;font-size:12px!important}
[data-testid="stSidebar"] strong,[data-testid="stSidebar"] b,
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,
  [data-testid="stSidebar"] h3{color:var(--text)!important}
[data-testid="stSidebar"] input{
  background:#fffdf7!important;border:1px solid var(--border-strong)!important;
  color:var(--text)!important;border-radius:5px!important;font-size:12px!important}
[data-testid="stSidebar"] input:focus{border-color:var(--primary)!important}

.side-brand{
  padding:4px 0 18px;border-bottom:1px solid var(--border);margin-bottom:14px}
.side-brand-row{display:flex;align-items:center;gap:10px}
.side-logo{
  width:36px;height:36px;background:linear-gradient(135deg,#e9f8e8,#f5f0d8);
  border-radius:12px;border:1px solid #cfe9c7;
  display:flex;align-items:center;justify-content:center;font-size:15px;font-weight:800;color:#3f9b5a;
  box-shadow:0 10px 24px rgba(83,139,82,0.14)}
.side-title{font-size:15px;font-weight:750;color:var(--text)}
.side-sub{font-size:11px;color:var(--muted);margin-top:2px}
.side-nav-group{
  color:#7e92a6;font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:0.09em;margin:14px 0 8px}
.side-nav-item{
  display:flex;align-items:center;gap:9px;padding:9px 10px;border-radius:8px;
  color:var(--text-soft);font-size:12px;font-weight:600;margin-bottom:4px;
  border:1px solid transparent}
.side-nav-item.active{
  background:var(--primary-soft);border-color:#cfe9c7;color:#2f7f47;
  box-shadow:inset 3px 0 0 var(--primary)}
.side-nav-item.muted{font-weight:500;color:var(--muted)}
.side-dot{
  width:18px;height:18px;border-radius:6px;background:#fff;border:1px solid var(--border);
  display:flex;align-items:center;justify-content:center;color:#089181;font-size:11px;flex-shrink:0}
[data-testid="stSidebar"] .stButton>button{
  width:100%!important;justify-content:flex-start!important;text-align:left!important;
  background:transparent!important;border:1px solid transparent!important;
  border-radius:9px!important;color:var(--text-soft)!important;
  box-shadow:none!important;font-weight:700!important;margin:1px 0!important;
  padding:9px 10px!important}
[data-testid="stSidebar"] .stButton>button:hover{
  background:#f6fbf0!important;border-color:var(--border)!important;
  color:#2f7f47!important;box-shadow:none!important}
[data-testid="stSidebar"] [role="radiogroup"]{
  display:flex!important;flex-direction:column!important;gap:4px!important}
[data-testid="stSidebar"] [role="radiogroup"] label{
  width:100%!important;margin:0!important;padding:9px 10px!important;
  border-radius:8px!important;border:1px solid transparent!important;
  background:transparent!important;color:var(--text-soft)!important}
[data-testid="stSidebar"] [role="radiogroup"] label:hover{
  background:#f6fbf0!important;border-color:var(--border)!important}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked){
  background:linear-gradient(90deg,var(--primary-soft),#f7f2de)!important;border-color:#cfe9c7!important;
  box-shadow:inset 3px 0 0 var(--primary),0 8px 20px rgba(83,139,82,0.08)!important}
[data-testid="stSidebar"] [role="radiogroup"] label p{
  color:var(--text-soft)!important;font-size:12px!important;font-weight:650!important}
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{
  color:#2f7f47!important}

p,span,div,li{color:var(--muted)!important;font-size:13px!important}
h1{font-size:1.4rem!important;font-weight:600!important;color:var(--text)!important;letter-spacing:-0.02em!important}
h2{font-size:1.05rem!important;font-weight:600!important;color:var(--text)!important}
h3{font-size:0.9rem!important;font-weight:500!important;color:var(--text)!important}
label{color:var(--text-soft)!important;font-size:13px!important;font-weight:500!important}
strong,b{color:var(--text)!important}
code{background:var(--surface)!important;color:var(--primary)!important;border:1px solid var(--border-strong)!important;
  border-radius:4px!important;padding:1px 5px!important;font-size:11px!important;
  font-family:'JetBrains Mono',monospace!important}

.stTextInput>div>div,.stTextInput>div>div>input,
.stTextArea>div>div,.stTextArea>div>div>textarea,
.stNumberInput>div>div>div,.stNumberInput>div>div>div>div,
.stDateInput>div>div>div>div{
  background:var(--surface)!important;border:1px solid var(--border-strong)!important;
  border-radius:9px!important;color:var(--text)!important;font-size:13px!important}
.stTextInput>div>div>input:focus,.stTextArea>div>div>textarea:focus{
  border-color:var(--primary)!important;box-shadow:0 0 0 3px rgba(105,201,135,0.16)!important}
.stTextInput>div>div>input::placeholder,.stTextArea>div>div>textarea::placeholder{
  color:var(--muted-deep)!important}

[data-testid="stFileUploader"]{
    background:var(--surface)!important;
    border-radius:6px!important;
}
[data-testid="stFileUploaderDropzone"]{
    border:1.5px dashed var(--border-strong)!important;
    border-radius:6px!important;
    background:#f8fdff!important;
    padding:18px!important;
    display:flex!important;
    align-items:center!important;
    gap:12px!important;
}
[data-testid="stFileUploaderDropzone"]:hover{
    border-color:var(--primary)!important;
}
[data-testid="stFileUploader"] section button{
    font-size:0 !important;
    color:transparent !important;
}
[data-testid="stFileUploader"] section button *{
    display:none !important;
}
[data-testid="stFileUploader"] section button::after{
    content:"Upload";
    font-size:14px !important;
    color:var(--text-soft) !important;
    font-weight:500 !important;
    display:block !important;
    line-height:1 !important;
}
[data-testid="stFileUploader"] button{
    background:#f7fbff !important;
    border:1px solid var(--border-strong) !important;
    border-radius:5px !important;
    min-height:42px !important;
    padding:8px 18px !important;
}

.stButton>button{
  background:rgba(255,255,255,0.9)!important;border:1px solid var(--border-strong)!important;
  border-radius:8px!important;color:var(--text-soft)!important;font-size:13px!important;
  font-weight:500!important;padding:0.5rem 1.2rem!important;box-shadow:none!important;
  transition:all 0.18s ease!important}
.stButton>button:hover{
  background:#f6fbf0!important;border-color:var(--primary)!important;color:var(--text)!important;
  box-shadow:0 8px 22px rgba(83,139,82,0.10)!important}
.stButton>button[kind="primary"]{
  background:linear-gradient(135deg,#88d99d,#69c987)!important;border-color:transparent!important;color:#17341e!important;font-weight:700!important;
  box-shadow:0 12px 28px rgba(83,139,82,0.16)!important}
.stButton>button[kind="primary"]:hover{background:linear-gradient(135deg,var(--primary-hover),#9bdc78)!important;color:#17341e!important}

[data-testid="metric-container"],[data-testid="stMetric"]{
  background:rgba(255,253,247,0.84)!important;border:1px solid rgba(232,226,210,0.96)!important;
  border-radius:10px!important;padding:0.85rem 1rem!important;box-shadow:none!important;
  border-left:3px solid var(--primary)!important}
[data-testid="stMetricLabel"] p,[data-testid="stMetricLabel"] div{
  color:var(--muted-deep)!important;font-size:11px!important;text-transform:uppercase!important;
  letter-spacing:0.04em!important;font-weight:500!important}
[data-testid="stMetricValue"] div{color:var(--text)!important;font-size:1.8rem!important;font-weight:600!important}
[data-testid="stMetricDelta"] svg{display:none!important}
[data-testid="stMetricDelta"]{font-size:11px!important}

[data-testid="stExpander"]{
    background:var(--surface)!important;
    border:1px solid var(--border)!important;
    border-radius:10px!important;
    margin-bottom:10px!important;
    overflow:hidden!important;box-shadow:none!important;
}
[data-testid="stExpander"] summary{
    padding:14px 18px 14px 42px!important;
    font-size:13px!important;
    color:var(--text)!important;
    background:var(--surface)!important;
    cursor:pointer!important;
    list-style:none!important;
}
[data-testid="stExpander"] summary::-webkit-details-marker{
    display:none!important;
}
[data-testid="stExpander"] summary::before{
    content:"▶";
    position:absolute!important;
    left:16px!important;
    top:14px!important;
    color:var(--primary)!important;
    font-size:11px!important;
}
[data-testid="stExpander"][open] summary::before{
    content:"▼";
}
[data-testid="stExpander"] > details > div{
    padding:14px 18px!important;
    background:#f8fdff!important;
}

[data-testid="stAlert"]{border-radius:4px!important;font-size:13px!important;border-left-width:3px!important}
.stSuccess{background:rgba(143,207,98,0.1)!important;border-color:var(--success)!important}
.stSuccess *{color:var(--success)!important}
.stInfo{background:rgba(105,201,135,0.10)!important;border-color:var(--primary)!important}
.stInfo *{color:var(--primary)!important}
.stWarning{background:rgba(216,185,79,0.1)!important;border-color:var(--warning)!important}
.stWarning *{color:var(--warning)!important}
.stError{background:rgba(218,54,51,0.1)!important;border-color:#da3633!important}
.stError *{color:#f85149!important}

.stProgress>div>div{background:var(--border)!important;border-radius:3px!important;height:4px!important}
.stProgress>div>div>div{background:var(--primary)!important;border-radius:3px!important}

[data-testid="stSelectbox"]>div>div,
[data-testid="stMultiSelect"]>div{
  background:var(--surface)!important;border:1px solid var(--border-strong)!important;
  border-radius:8px!important;color:var(--text)!important}
[data-testid="stSelectbox"] *{color:var(--text)!important;background:var(--surface)!important}
[data-testid="stMultiSelect"] span[data-baseweb="tag"]{
  background:rgba(105,201,135,0.12)!important;color:#2f7f47!important;
  border:1px solid rgba(105,201,135,0.30)!important;border-radius:6px!important;font-size:11px!important}

[data-testid="stRadio"]>div{gap:8px!important;background:transparent!important}
[data-testid="stRadio"] label{color:var(--text-soft)!important;font-size:13px!important}
[data-testid="stRadio"] [role="radiogroup"]{
  gap:8px!important}
[data-testid="stRadio"] [role="radiogroup"][aria-orientation="horizontal"]{
  background:rgba(255,253,247,0.78)!important;border:1px solid var(--border)!important;
  border-radius:13px!important;padding:4px!important}
[data-testid="stRadio"] [role="radiogroup"][aria-orientation="horizontal"] label{
  border-radius:10px!important;padding:8px 12px!important;border:1px solid transparent!important;
  margin:0!important;background:transparent!important}
[data-testid="stRadio"] [role="radiogroup"][aria-orientation="horizontal"] label:has(input:checked){
  background:linear-gradient(135deg,var(--primary-soft),#f7f2de)!important;
  border-color:#cfe9c7!important;box-shadow:0 8px 18px rgba(83,139,82,0.08)!important}
[data-testid="stRadio"] [role="radiogroup"][aria-orientation="horizontal"] label:has(input:checked) p{
  color:#2f7f47!important;font-weight:750!important}

[data-testid="stSegmentedControl"]{
  margin:2px 0 18px!important}
[data-testid="stSegmentedControl"] > div{
  background:rgba(255,253,247,0.82)!important;border:1px solid var(--border)!important;
  border-radius:16px!important;padding:4px!important;box-shadow:0 10px 24px rgba(75,70,48,0.04)!important}
[data-testid="stSegmentedControl"] button{
  border-radius:12px!important;border:1px solid transparent!important;
  color:var(--muted)!important;font-weight:700!important;min-height:34px!important}
[data-testid="stSegmentedControl"] button[aria-pressed="true"],
[data-testid="stSegmentedControl"] button[aria-selected="true"]{
  background:linear-gradient(135deg,var(--primary-soft),#f7f2de)!important;
  border-color:#cfe9c7!important;color:#2f7f47!important;
  box-shadow:0 8px 18px rgba(83,139,82,0.08)!important}

[data-testid="stSlider"]>div>div{background:var(--border-strong)!important}
[data-testid="stSlider"] [role="slider"]{background:var(--primary)!important;border-color:var(--primary)!important}

[data-testid="stDownloadButton"]>button{
  background:rgba(143,207,98,0.1)!important;border:1px solid var(--success)!important;
  color:var(--success)!important;font-weight:500!important;border-radius:5px!important;font-size:13px!important}
[data-testid="stDownloadButton"]>button:hover{background:rgba(143,207,98,0.2)!important}

[data-testid="stPlotlyChart"]{
  background:var(--surface)!important;border:1px solid var(--border)!important;
  border-radius:14px!important;overflow:hidden!important;box-shadow:var(--blue-glow)!important}

hr{border:none!important;border-top:1px solid var(--border)!important;margin:1rem 0!important}
[data-testid="column"]{padding:0 6px!important}
[data-testid="stVerticalBlockBorderWrapper"],
[data-testid="stForm"]{
  background:rgba(255,253,247,0.88)!important;border:1px solid var(--border)!important;
  border-radius:18px!important;box-shadow:var(--shadow)!important}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"]{
  gap:0.45rem!important}

::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--border-strong);border-radius:2px}
::-webkit-scrollbar-thumb:hover{background:var(--primary)}

/* Section tabs */
[data-testid="stTabs"]{background:transparent!important}
[data-testid="stTabs"] [role="tablist"]{
  background:rgba(255,255,255,0.72)!important;
  border:1px solid var(--border)!important;border-radius:12px!important;
  padding:4px!important;margin:4px 0 22px!important;
  display:flex!important;gap:6px!important}
[data-testid="stTabs"] button[data-baseweb="tab"]{
  background:transparent!important;border:1px solid transparent!important;border-radius:9px!important;
  padding:11px 14px!important;font-weight:650!important;font-size:13px!important;
  color:var(--muted)!important;transition:all 0.15s!important;
  flex:1!important;text-align:center!important;box-shadow:none!important}
[data-testid="stTabs"] button[data-baseweb="tab"]:hover{
  background:#f6fbf0!important;color:var(--text-soft)!important;
  border-color:var(--border)!important;transform:none!important}
[data-testid="stTabs"] button[data-baseweb="tab"][aria-selected="true"]{
  background:linear-gradient(135deg,var(--primary-soft),#f7f2de)!important;color:#2f7f47!important;
  border:1px solid #cfe9c7!important;
  box-shadow:none!important}
[data-testid="stTabs"] button[data-baseweb="tab"] p{
  font-size:13px!important;font-weight:650!important}

/* Card component */
.tp-card{
  background:var(--surface)!important;border:1px solid var(--border)!important;
  border-radius:16px!important;padding:18px!important;margin-bottom:12px!important;
  transition:border-color 0.18s ease!important;box-shadow:var(--shadow)!important}
.tp-card:hover{border-color:#cfe9c7!important;transform:none!important}
.tp-card-title{
  font-size:15px!important;font-weight:600!important;color:var(--text)!important;
  margin-bottom:4px!important}
.tp-card-headline{
  font-size:12px!important;color:var(--muted)!important;margin-bottom:10px!important;
  font-family:'JetBrains Mono',monospace!important}

/* KPI mini cards */
.kpi-card{
  background:rgba(255,253,247,0.86);border:1px solid var(--border);
  border-radius:16px;padding:16px;margin:2px 0 12px;box-shadow:var(--shadow)}
.kpi-label{font-size:10px;color:var(--muted-deep);text-transform:uppercase;
  letter-spacing:0.08em;font-family:'JetBrains Mono',monospace;margin-bottom:6px}
.kpi-value{font-size:1.6rem;font-weight:700;color:var(--text);line-height:1}
.kpi-sub{font-size:11px;color:var(--muted);margin-top:4px}

/* Insight pill */
.insight{border-radius:10px;padding:12px 16px;margin-bottom:8px;
  display:flex;gap:10px;align-items:flex-start;border:1px solid}
.insight-icon{font-size:18px;flex-shrink:0;margin-top:1px}
.insight-title{font-size:13px;font-weight:600;color:var(--text);margin-bottom:2px}
.insight-detail{font-size:12px;color:var(--muted);line-height:1.5}

/* Skill tag */
.skill-tag{
  display:inline-block;padding:3px 9px;border-radius:4px;
  font-size:11px;font-weight:500;margin:2px 3px 2px 0;
  background:rgba(105,201,135,0.11);color:#2f7f47;
  border:1px solid rgba(105,201,135,0.28)}

/* Light-theme compatibility for legacy inline cards */
div[style*="background:#ffffff"],
div[style*="background: #ffffff"],
div[style*="background:#f5f8f4"],
div[style*="background: #f5f8f4"],
div[style*="background:#111827"]{
  background:var(--surface)!important;
  border-color:var(--border)!important;
  box-shadow:none!important}
div[style*="border:1px solid #e4ebe5"],
div[style*="border:1px solid #d5dfd7"]{border-color:var(--border)!important}
div[style*="border-top:1px solid #e4ebe5"],
div[style*="border-bottom:1px solid #e4ebe5"]{border-color:var(--border)!important}

.module-overview{
  display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:0 0 18px}
.overview-card{
  background:rgba(255,255,255,0.9);border:1px solid var(--border);border-radius:16px;
  padding:18px 18px 16px;box-shadow:0 12px 30px rgba(91,72,28,0.05)}
.overview-card.active{border-color:#cfe9c7;box-shadow:inset 0 -3px 0 var(--primary),0 14px 34px rgba(83,139,82,0.10)}
.overview-icon{
  width:38px;height:38px;border-radius:12px;background:var(--primary-soft);
  display:flex;align-items:center;justify-content:center;color:#219558;font-size:18px;margin-bottom:12px}
.overview-title{font-size:15px;font-weight:750;color:var(--text);margin-bottom:5px}
.overview-sub{font-size:12px;color:var(--muted);line-height:1.5}
.section-label{
  display:flex;align-items:center;min-height:28px;
  border-left:3px solid var(--primary);padding:4px 0 4px 10px;
  margin:10px 0 10px;font-size:12px;font-weight:700;color:var(--text);
  letter-spacing:0.01em}
.step-header{
  display:flex;align-items:center;gap:10px;margin:18px 0 12px;
  padding:12px 14px;border:1px solid var(--border);border-radius:16px;background:rgba(255,253,247,0.78);box-shadow:var(--shadow)}
.step-index{
  min-width:28px;height:28px;padding:0 8px;background:var(--primary-soft);
  border:1px solid #cfe9c7;border-radius:9px;display:flex;align-items:center;
  justify-content:center;font-size:12px;font-weight:800;color:#2f7f47}
.step-title{font-size:15px;font-weight:760;color:var(--text)}
.candidate-header{
  padding:14px 16px;border:1px solid var(--border);
  border-left:4px solid var(--primary);border-radius:12px;
  background:rgba(255,255,255,0.9);margin:10px 0 18px;box-shadow:0 10px 24px rgba(20,34,51,0.045)}
.candidate-header-name{font-size:20px;font-weight:700;color:var(--text)}
.candidate-header-meta{font-size:12px;color:var(--muted);margin-top:4px}
.sourcing-flow{
  display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:4px 0 18px}
.sourcing-step{
  background:rgba(255,255,255,0.76);border:1px solid var(--border);
  border-radius:14px;padding:10px 14px;text-align:center;color:var(--muted);
  font-size:12px;font-weight:700}
.sourcing-step.active{
  background:linear-gradient(135deg,var(--primary-soft),var(--primary-2-soft));
  border-color:#cfe9c7;color:#2f7f47;box-shadow:0 10px 24px rgba(83,139,82,0.10)}
.sourcing-card-title{
  display:flex;align-items:center;gap:10px;font-size:15px;font-weight:780;color:var(--text);
  margin-bottom:4px}
.sourcing-card-icon{
  width:30px;height:30px;border-radius:10px;background:linear-gradient(135deg,var(--primary-soft),#f7f2de);
  border:1px solid #cfe9c7;display:inline-flex;align-items:center;justify-content:center;color:#2f7f47;
  font-size:14px;font-weight:800;box-shadow:0 8px 18px rgba(83,139,82,0.10)}
.sourcing-card-sub{font-size:12px;color:var(--muted);margin-bottom:14px}
.method-card{
  background:rgba(255,255,255,0.74);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px;margin-bottom:10px}
.method-card-title{font-size:13px;font-weight:700;color:var(--text);margin-bottom:4px}
.method-card-sub{font-size:12px;color:var(--muted);line-height:1.5}
.strategy-status{
  display:flex;align-items:center;justify-content:space-between;gap:12px;
  padding:12px 14px;border:1px solid var(--border);border-radius:12px;
  background:linear-gradient(135deg,rgba(255,253,247,0.9),rgba(246,251,240,0.78));
  margin:10px 0 12px}
.strategy-status-title{font-size:13px;font-weight:760;color:var(--text);margin-bottom:3px}
.strategy-status-meta{font-size:11px;color:var(--muted);line-height:1.45}
.strategy-status-pill{
  flex-shrink:0;padding:5px 9px;border-radius:999px;background:var(--primary-soft);
  border:1px solid #cfe9c7;color:#2f7f47;font-size:11px;font-weight:700}
.strategy-mini-grid{
  display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:10px 0}
.strategy-mini-card{
  border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,0.68);
  padding:10px 12px;min-height:64px}
.strategy-mini-label{
  font-size:10px;color:var(--muted-deep);text-transform:uppercase;letter-spacing:0.06em;
  font-family:'JetBrains Mono',monospace;margin-bottom:5px}
.strategy-mini-value{font-size:12px;color:var(--text-soft);line-height:1.45}
.strategy-block{
  border:1px solid var(--border);border-radius:14px;background:rgba(255,253,247,0.70);
  padding:12px 14px;margin:10px 0}
.strategy-block-title{font-size:12px;font-weight:760;color:var(--text);margin-bottom:8px}
.strategy-source-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:4px}
.strategy-source-pill{
  display:inline-flex;align-items:center;padding:4px 9px;border-radius:999px;
  background:var(--primary-2-soft);border:1px solid #d6eac6;color:#447b2f;
  font-size:11px;font-weight:650}
.strategy-risk-list{margin:0;padding-left:16px}
.strategy-risk-list li{font-size:12px;color:var(--text-soft);line-height:1.55;margin:4px 0}
.source-readiness-grid{
  display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:10px 0 14px}
.source-readiness-card{
  border:1px solid var(--border);border-radius:14px;background:rgba(255,253,247,0.72);
  padding:12px 14px;min-height:86px}
.source-readiness-title{font-size:12px;font-weight:800;color:var(--text);margin-bottom:5px}
.source-readiness-meta{font-size:11px;color:var(--muted);line-height:1.45}
.source-readiness-pill{
  display:inline-flex;align-items:center;padding:3px 8px;border-radius:999px;
  font-size:10px;font-weight:800;margin-top:8px;border:1px solid transparent}
.source-readiness-pill.ready{background:var(--primary-soft);border-color:#cfe9c7;color:#2f7f47}
.source-readiness-pill.warn{background:#fff4d7;border-color:#ead99a;color:#8a6a12}
.source-readiness-pill.off{background:#f2f5f2;border-color:#dfe6e0;color:#718078}
.sourcing-dashboard-note{
  border:1px dashed var(--border-strong);border-radius:14px;background:rgba(255,253,247,0.56);
  padding:12px 14px;color:var(--muted);font-size:12px;line-height:1.6;margin:8px 0 14px}

/* Light data tables and popovers */
[data-testid="stDataFrame"],[data-testid="stTable"]{
  background:var(--surface)!important;border:1px solid var(--border)!important;
  border-radius:6px!important;overflow:hidden!important}
[data-baseweb="popover"],[role="listbox"]{
  background:var(--surface)!important;color:var(--text)!important;
  border-color:var(--border)!important;box-shadow:0 12px 30px rgba(31,56,41,0.12)!important}

.workspace-titlebar{
  display:flex;align-items:center;justify-content:space-between;gap:18px;
  margin:0 0 18px;padding:2px 0 4px}
.workspace-title-left{display:flex;align-items:center;gap:12px;min-width:0}
.workspace-logo{
  width:34px;height:34px;border-radius:12px;background:linear-gradient(135deg,#e9f8e8,#f7f2de);
  border:1px solid #cfe9c7;display:flex;align-items:center;justify-content:center;
  color:#2f7f47;font-size:16px;font-weight:850;box-shadow:0 10px 22px rgba(83,139,82,0.10)}
.workspace-title{font-size:22px;font-weight:850;color:var(--text);letter-spacing:-0.03em;line-height:1.15}
.workspace-subtitle{font-size:12px;color:var(--muted);margin-top:3px}
.workspace-help{
  flex-shrink:0;padding:8px 12px;border-radius:999px;background:rgba(255,253,247,0.82);
  border:1px solid var(--border);color:var(--text-soft);font-size:12px;font-weight:700}
"""
st.markdown(f"<style>{_css}</style>", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def section_label(text):
    st.markdown(
        f'<div class="section-label">{text}</div>',
        unsafe_allow_html=True)

def badge_html(text, color="gray"):
    C = {
        "green":  ("rgba(48,184,106,0.10)","#30a862","rgba(48,184,106,0.28)"),
        "blue":   ("rgba(79,143,247,0.10)","#3979d9","rgba(79,143,247,0.25)"),
        "amber":  ("rgba(212,167,44,0.10)","#a87d13","rgba(212,167,44,0.28)"),
        "red":    ("rgba(218,54,51,0.15)","#f85149","rgba(218,54,51,0.4)"),
        "purple": ("rgba(139,92,246,0.10)","#7c4ee3","rgba(139,92,246,0.25)"),
        "gray":   ("#f2f5f2","#718078","#dfe6e0"),
    }
    bg,tc,bc = C.get(color, C["gray"])
    return (f'<span style="display:inline-flex;align-items:center;padding:2px 10px;'
            f'border-radius:4px;font-size:11px;font-weight:500;background:{bg};'
            f'color:{tc};border:1px solid {bc};margin:2px">{text}</span>')

def score_color(s):
    return "#30b86a" if s>=7 else "#d4a72c" if s>=5 else "#f85149"

def score_bar_color(s):
    return "#6fa845" if s>=7 else "#ad8d2f" if s>=5 else "#da3633"

def dim_row_html(label, weight, score, justification):
    pct = score * 10
    sc  = score_color(score)
    bc  = score_bar_color(score)
    return f"""
    <div style="display:grid;grid-template-columns:155px 32px 100px 34px 1fr;
                gap:8px;align-items:center;padding:7px 0;
                border-bottom:1px solid #313b26">
      <span style="font-size:12px;color:#dce5c8">{label}</span>
      <span style="font-size:11px;color:#68745a;text-align:center;
                   font-family:JetBrains Mono,monospace">{weight}</span>
      <div style="height:4px;background:#313b26;border-radius:2px;overflow:hidden">
        <div style="width:{pct}%;height:100%;background:{bc};border-radius:2px"></div>
      </div>
      <span style="font-size:12px;font-weight:600;color:{sc};text-align:right">{score:.1f}</span>
      <span style="font-size:11px;color:#68745a;line-height:1.4">{justification}</span>
    </div>"""

def iq_block_html(label, question, accent="#4f8ff7", label_color="#3979d9"):
    return f"""
    <div style="background:#171d12;border:1px solid #313b26;
                border-left:3px solid {accent};border-radius:0 8px 8px 0;
                padding:10px 14px;margin:5px 0">
      <div style="font-size:10px;font-weight:500;color:{label_color};
                  text-transform:uppercase;letter-spacing:0.06em;
                  margin-bottom:4px;font-family:JetBrains Mono,monospace">{label}</div>
      <div style="font-size:12px;color:#dce5c8;line-height:1.5">{question}</div>
    </div>"""

def step_header(num, title):
    st.markdown(f"""
    <div class="step-header">
      <div class="step-index">{num}</div>
      <div class="step-title">{title}</div>
    </div>""", unsafe_allow_html=True)

def _kpi(label, value, sub="", color="#eef3df"):
    return f"""
    <div class="kpi-card">
      <div class="kpi-label">{label}</div>
      <div class="kpi-value" style="color:{color}">{value}</div>
      {f'<div class="kpi-sub">{sub}</div>' if sub else ''}
    </div>"""

def page_titlebar(module_name: str):
    config = {
        "JD 生成": (
            "JD 生成",
            "岗位需求生成、人工确认与岗位目录管理",
            "生成 → 审核 → 入目录",
        ),
        "简历筛选": (
            "简历筛选",
            "选择岗位、上传简历并完成人岗匹配",
            "岗位 → 匹配 → 分层",
        ),
        "人才开源": (
            "人才开源",
            "公开检索、证据核验与人工入库",
            "画像 → 线索 → 入库",
        ),
        "岗位库": (
            "岗位库",
            "管理已确认岗位 JD，并供简历筛选与人才开源调用",
            "确认 JD → 版本管理 → 业务调用",
        ),
        "人才库": (
            "人才库",
            "区分内部 People API 与外部人工确认入库人才",
            "内部授权 → 外部沉淀 → 统一检索",
        ),
        "反馈追踪": (
            "反馈追踪",
            "沉淀候选人后续结果，并为 Skill 调优提供样本",
            "反馈记录 → 满 20 条 → 人工确认调优",
        ),
        "Workflow / Matching": (
            "Workflow / Matching",
            "集中查看 Workflow 调用链路与 Matching 评分规则",
            "Workflow 调用 → Matching 评分 → 人工确认修改",
        ),
    }
    title, subtitle, flow = config.get(module_name, (module_name, "", ""))
    st.markdown(
        f"""
        <div class="workspace-titlebar">
          <div class="workspace-title-left">
            <div class="workspace-logo">T</div>
            <div>
              <div class="workspace-title">{html.escape(title)}</div>
              <div class="workspace-subtitle">{html.escape(subtitle)}</div>
            </div>
          </div>
          <div class="workspace-help">{html.escape(flow)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _insight_html(severity: str, title: str, detail: str):
    MAP = {
        "success": ("✅", "rgba(35,134,54,0.08)", "#239657", "rgba(35,134,54,0.25)"),
        "warning": ("⚠️", "rgba(210,153,34,0.08)", "#d29922", "rgba(210,153,34,0.25)"),
        "info":    ("ℹ️", "rgba(31,111,235,0.08)", "#1f6feb", "rgba(31,111,235,0.25)"),
    }
    icon, bg, tc, bc = MAP.get(severity, MAP["info"])
    return f"""
    <div class="insight" style="background:{bg};border-color:{bc}">
      <div class="insight-icon">{icon}</div>
      <div style="flex:1;min-width:0">
        <div class="insight-title" style="color:{tc}">{title}</div>
        <div class="insight-detail">{detail}</div>
      </div>
    </div>"""

def _skill_tags(skills, max_show=12):
    tags = ""
    for s in skills[:max_show]:
        tags += f'<span class="skill-tag">{s}</span>'
    if len(skills) > max_show:
        tags += f'<span class="skill-tag" style="background:#e4ebe5;color:#718078;border-color:#d5dfd7">+{len(skills)-max_show}</span>'
    return tags

def _compact_text(value, max_len=110):
    if value is None:
        text = "—"
    elif isinstance(value, (list, tuple, set)):
        text = "、".join(str(v) for v in value if str(v).strip()) or "—"
    elif isinstance(value, dict):
        text = "；".join(f"{k}: {v}" for k, v in value.items()) or "—"
    else:
        text = str(value).strip() or "—"
    text = " ".join(text.split())
    if len(text) > max_len:
        text = text[:max_len].rstrip() + "..."
    return html.escape(text)


def _sourcing_source_readiness_cards() -> str:
    scholar_names = configured_google_scholar_provider_names()
    sources = [
        {
            "name": "GitHub API",
            "status": "ready" if os.environ.get("GITHUB_TOKEN", "").strip() else "warn",
            "pill": "已配置 Token" if os.environ.get("GITHUB_TOKEN", "").strip() else "可用但易限流",
            "meta": "检索公开仓库与 README，用于判断项目是否真有实现。",
        },
        {
            "name": "arXiv API",
            "status": "ready",
            "pill": "公开 API",
            "meta": "检索公开论文与作者线索，适合科研/算法方向补充。",
        },
        {
            "name": "Google Scholar",
            "status": "ready" if scholar_names else "off",
            "pill": "已配置" if scholar_names else "未配置",
            "meta": f"当前服务商：{', '.join(scholar_names)}" if scholar_names else "需配置 SerpAPI、SerpDog 或 ScrapingBee。",
        },
        {
            "name": "People API",
            "status": "ready" if people_system_enabled() else "off",
            "pill": "已接入" if people_system_enabled() else "未接入",
            "meta": "接入后才展示内部人才库，不使用本地演示数据冒充。",
        },
    ]
    cards = ""
    for source in sources:
        cards += f"""
        <div class="source-readiness-card">
          <div class="source-readiness-title">{html.escape(source["name"])}</div>
          <div class="source-readiness-meta">{html.escape(source["meta"])}</div>
          <span class="source-readiness-pill {source["status"]}">{html.escape(source["pill"])}</span>
        </div>
        """
    return f'<div class="source-readiness-grid">{cards}</div>'


def _sourcing_task_progress_rows(tasks: list[dict]) -> list[dict]:
    rows = []
    for task in tasks:
        candidates = list_sourcing_candidates(task_id=task["id"], limit=1000)
        by_status = {}
        for candidate in candidates:
            status = candidate.get("decision_status") or "待确认"
            by_status[status] = by_status.get(status, 0) + 1
        rows.append({
            "任务 ID": task["id"],
            "任务名称": task.get("task_name", ""),
            "状态": task.get("status", ""),
            "方向": task.get("talent_direction", ""),
            "级别": task.get("target_level", ""),
            "候选线索": len(candidates),
            "待确认": by_status.get("待确认", 0),
            "重点关注": by_status.get("重点关注", 0),
            "已入库": by_status.get("已入库", 0),
            "暂不处理": by_status.get("暂不处理", 0),
            "关联岗位": task.get("linked_job_profile_id", ""),
            "更新时间": task.get("updated_at", ""),
        })
    return rows


def _sourcing_candidate_export_rows(candidates: list[dict]) -> list[dict]:
    rows = []
    for candidate in candidates:
        evidence_urls = []
        for ev in candidate.get("evidence_links") or []:
            if isinstance(ev, dict) and ev.get("url"):
                evidence_urls.append(ev["url"])
        rows.append({
            "candidate_id": candidate.get("id"),
            "candidate_name": candidate.get("candidate_name", ""),
            "current_org": candidate.get("current_org", ""),
            "match_score": candidate.get("match_score", 0),
            "recommendation_level": candidate.get("recommendation_level", ""),
            "decision_status": candidate.get("decision_status", ""),
            "source_origin_type": candidate.get("source_origin_type", ""),
            "authenticity_status": candidate.get("authenticity_status", ""),
            "direction_tags": "、".join(candidate.get("direction_tags") or []),
            "recommendation_reason": candidate.get("recommendation_reason", ""),
            "uncertainties": " | ".join(candidate.get("uncertainties") or []),
            "evidence_urls": " | ".join(evidence_urls),
            "hr_note": candidate.get("hr_note", ""),
            "updated_at": candidate.get("updated_at", ""),
        })
    return rows


FEEDBACK_REASON_TAGS = [
    "技术深度不足",
    "项目不匹配",
    "工程能力不足",
    "算法能力不足",
    "业务理解不足",
    "沟通表达一般",
    "稳定性风险",
    "经验年限不匹配",
    "学历/院校不匹配",
    "简历信息不足",
    "意愿/薪资不匹配",
    "通过反馈",
]


def _feedback_reason_text(item: dict) -> str:
    return str(item.get("fail_reason") or item.get("hr_note") or "").strip()


def _is_valid_optimization_sample(item: dict) -> bool:
    return (
        item.get("current_status") == "已反馈"
        and bool(str(item.get("final_result") or "").strip())
        and bool(_feedback_reason_text(item))
    )


def _infer_feedback_tags(item: dict) -> list[str]:
    text = " ".join([
        _feedback_reason_text(item),
        str(item.get("final_result", "")),
        str(item.get("business_review_result", "")),
        str(item.get("interview_stage", "")),
    ]).lower()
    mapping = {
        "技术深度不足": ["技术深度", "深度不足", "技术不行", "基础不扎实"],
        "项目不匹配": ["项目不匹配", "方向不匹配", "业务不匹配", "经历不匹配"],
        "工程能力不足": ["工程", "coding", "代码", "系统设计", "开发能力"],
        "算法能力不足": ["算法", "模型", "推理", "训练", "数学"],
        "业务理解不足": ["业务理解", "业务", "场景理解"],
        "沟通表达一般": ["沟通", "表达", "协作"],
        "稳定性风险": ["稳定", "跳槽", "意愿", "风险"],
        "经验年限不匹配": ["年限", "级别", "资深度", "senior"],
        "学历/院校不匹配": ["学历", "学校", "院校", "专业"],
        "简历信息不足": ["信息不足", "不完整", "无法判断", "证据不足"],
        "意愿/薪资不匹配": ["薪资", "base", "意愿", "地点", "到岗"],
    }
    tags = []
    for tag, needles in mapping.items():
        if any(needle in text for needle in needles):
            tags.append(tag)
    if "通过" in str(item.get("final_result", "")) and "未通过" not in str(item.get("final_result", "")):
        tags.append("通过反馈")
    return tags or ["未归类"]


def _feedback_outcome_bucket(item: dict) -> str:
    final_result = str(item.get("final_result") or "")
    if final_result == "通过面试":
        return "正样本"
    if final_result in {"未通过面试", "未通过业务筛选"}:
        return "负样本"
    return "待判断"


def _feedback_misjudgment_type(item: dict) -> str:
    decision = str(item.get("hr_screening_decision") or "")
    final_result = str(item.get("final_result") or "")
    if decision == "推荐" and final_result in {"未通过面试", "未通过业务筛选"}:
        return "高估风险"
    if decision == "不推荐" and final_result == "通过面试":
        return "低估风险"
    if decision == "待定" and final_result:
        return "边界样本"
    return "一致或待判断"


def _feedback_export_rows(items: list[dict]) -> list[dict]:
    rows = []
    for item in items:
        rows.append({
            "ID": item.get("id"),
            "候选人": item.get("candidate_name", ""),
            "岗位": item.get("job_title", ""),
            "部门": item.get("department", ""),
            "Skill ID": item.get("matching_skill_id", ""),
            "Skill": item.get("matching_skill_name", ""),
            "AI 评分": item.get("initial_score", 0),
            "AI 建议": item.get("initial_recommendation", ""),
            "HR 初筛": item.get("hr_screening_decision", ""),
            "梯队": item.get("talent_tier", ""),
            "状态": item.get("current_status", ""),
            "后续结果": item.get("final_result", ""),
            "样本类型": _feedback_outcome_bucket(item),
            "误判类型": _feedback_misjudgment_type(item),
            "原因标签": "、".join(_infer_feedback_tags(item)),
            "原因/备注": _feedback_reason_text(item),
            "有效调优样本": "是" if _is_valid_optimization_sample(item) else "否",
            "更新时间": item.get("updated_at", ""),
        })
    return rows


def _feedback_skill_summary(items: list[dict]) -> list[dict]:
    by_skill = {}
    for item in items:
        sid = item.get("matching_skill_id") or "unknown"
        bucket = by_skill.setdefault(sid, {
            "Skill ID": sid,
            "Skill": item.get("matching_skill_name") or sid,
            "全部记录": 0,
            "有效样本": 0,
            "正样本": 0,
            "负样本": 0,
            "高估风险": 0,
            "低估风险": 0,
            "边界样本": 0,
        })
        bucket["全部记录"] += 1
        if _is_valid_optimization_sample(item):
            bucket["有效样本"] += 1
        outcome = _feedback_outcome_bucket(item)
        if outcome in bucket:
            bucket[outcome] += 1
        misjudgment = _feedback_misjudgment_type(item)
        if misjudgment in bucket:
            bucket[misjudgment] += 1
    return list(by_skill.values())


def _build_skill_optimization_prompt(skill: dict, samples: list[dict]) -> str:
    anonymized_samples = []
    for item in samples[:40]:
        anonymized_samples.append({
            "job_title": item.get("job_title", ""),
            "initial_score": item.get("initial_score", 0),
            "ai_recommendation": item.get("initial_recommendation", ""),
            "hr_screening_decision": item.get("hr_screening_decision", ""),
            "talent_tier": item.get("talent_tier", ""),
            "final_result": item.get("final_result", ""),
            "reason_tags": _infer_feedback_tags(item),
            "reason": _feedback_reason_text(item),
            "misjudgment_type": _feedback_misjudgment_type(item),
            "score_snapshot": item.get("score_snapshot", {}),
        })
    return f"""
你是一名招聘评估体系优化专家，你的任务是基于匿名化招聘反馈样本，分析当前匹配 Skill 的误判规律，并生成可供 HR 审核的优化建议。

当前 Skill：
{json.dumps(skill, ensure_ascii=False, indent=2)}

匿名化反馈样本：
{json.dumps(anonymized_samples, ensure_ascii=False, indent=2)}

请只返回 JSON，不要返回 Markdown。JSON 字段：
{{
  "sample_summary": {{
    "total_samples": 0,
    "positive_samples": 0,
    "negative_samples": 0,
    "main_misjudgments": ["..."]
  }},
  "misjudgment_patterns": [
    {{"pattern": "...", "evidence": "...", "severity": "高/中/低"}}
  ],
  "weight_adjustment_suggestions": [
    {{"dimension": "...", "current_issue": "...", "suggestion": "..."}}
  ],
  "rule_change_suggestions": [
    {{"section": "正向信号/负向信号/证据规则/面试关注点", "action": "新增/修改/删除", "content": "...", "reason": "..."}}
  ],
  "risk_controls": ["..."],
  "requires_hr_confirmation": true
}}

要求：
- 只能生成建议，不要声称已修改 Skill。
- 不要输出候选人真实姓名。
- 如果样本量不足或信号弱，要明确提示不建议自动调权。
"""


def _fallback_skill_optimization_report(skill: dict, samples: list[dict]) -> dict:
    tag_counts = {}
    mis_counts = {}
    for item in samples:
        for tag in _infer_feedback_tags(item):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        mis = _feedback_misjudgment_type(item)
        mis_counts[mis] = mis_counts.get(mis, 0) + 1
    top_tags = sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    top_mis = sorted(mis_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
    return {
        "sample_summary": {
            "total_samples": len(samples),
            "positive_samples": sum(1 for item in samples if _feedback_outcome_bucket(item) == "正样本"),
            "negative_samples": sum(1 for item in samples if _feedback_outcome_bucket(item) == "负样本"),
            "main_misjudgments": [f"{name}: {count}" for name, count in top_mis],
        },
        "misjudgment_patterns": [
            {
                "pattern": f"{tag} 出现 {count} 次",
                "evidence": "来自 HR 后续反馈原因标签的聚合统计。",
                "severity": "高" if count >= 5 else "中" if count >= 2 else "低",
            }
            for tag, count in top_tags
        ],
        "weight_adjustment_suggestions": [
            {
                "dimension": "待 HR 审核",
                "current_issue": "当前样本量或标签分布需要人工复核。",
                "suggestion": "先查看误判样本详情，再决定是否调整权重或规则。",
            }
        ],
        "rule_change_suggestions": [
            {
                "section": "负向信号",
                "action": "新增/修改",
                "content": "结合高频失败原因补充更明确的风险识别规则。",
                "reason": "避免 AI 在初筛阶段高估表面匹配但后续失败的人选。",
            }
        ],
        "risk_controls": [
            "本报告只是建议草案，不会自动写入 Skill。",
            "样本量不足 20 条时不建议调整权重。",
        ],
        "requires_hr_confirmation": True,
    }


def _generate_skill_optimization_report(skill: dict, samples: list[dict]) -> dict:
    if not has_required_api_key():
        return _fallback_skill_optimization_report(skill, samples)
    try:
        raw = chat_completion(
            [
                {"role": "system", "content": "你只输出可解析 JSON。"},
                {"role": "user", "content": _build_skill_optimization_prompt(skill, samples)},
            ],
            max_tokens=2600,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start:end + 1])
    except Exception:
        pass
    return _fallback_skill_optimization_report(skill, samples)


def _load_module_prompt(module_name: str, attr_name: str) -> str:
    try:
        module = importlib.import_module(module_name)
        return str(getattr(module, attr_name, "") or "")
    except Exception as e:
        return f"读取失败：{e}"


def _runtime_prompt_registry() -> list[dict]:
    return [
        {
            "名称": "JD 解析 Prompt",
            "Workflow Skill": "JD 生成 Workflow Skill",
            "Workflow Skill ID": "jd_generation_workflow_skill",
            "模块": "JD 生成",
            "所属 Agent": "JD Parser Agent",
            "位置": "modules/jd_generation/jd_parser.py::_SYSTEM_PROMPT",
            "用途": "把 JD 文本解析成结构化岗位要求。",
            "Prompt": _load_module_prompt("modules.jd_generation.jd_parser", "_SYSTEM_PROMPT"),
        },
        {
            "名称": "JD 字段识别 Prompt",
            "Workflow Skill": "JD 生成 Workflow Skill",
            "Workflow Skill ID": "jd_generation_workflow_skill",
            "模块": "JD 生成",
            "所属 Agent": "JD Generation Agent",
            "位置": "modules/jd_generation/jd_generator.py::_FIELD_INFERENCE_PROMPT",
            "用途": "从极简自然语言招聘需求中识别岗位字段。",
            "Prompt": _load_module_prompt("modules.jd_generation.jd_generator", "_FIELD_INFERENCE_PROMPT"),
        },
        {
            "名称": "JD 生成 Prompt",
            "Workflow Skill": "JD 生成 Workflow Skill",
            "Workflow Skill ID": "jd_generation_workflow_skill",
            "模块": "JD 生成",
            "所属 Agent": "JD Generation Agent",
            "位置": "modules/jd_generation/jd_generator.py::_SYSTEM_PROMPT",
            "用途": "生成候选人可见 JD、内部岗位画像和筛选策略。",
            "Prompt": _load_module_prompt("modules.jd_generation.jd_generator", "_SYSTEM_PROMPT"),
        },
        {
            "名称": "简历解析 Prompt",
            "Workflow Skill": "简历筛选 Workflow Skill",
            "Workflow Skill ID": "resume_screening_workflow_skill",
            "模块": "简历筛选",
            "所属 Agent": "Profile Parser Agent",
            "位置": "modules/resume_screening/profile_parser.py::_SYSTEM_PROMPT",
            "用途": "把简历或 LinkedIn 文本解析成结构化候选人画像。",
            "Prompt": _load_module_prompt("modules.resume_screening.profile_parser", "_SYSTEM_PROMPT"),
        },
        {
            "名称": "人岗匹配评分 Prompt",
            "Workflow Skill": "简历筛选 Workflow Skill",
            "Workflow Skill ID": "resume_screening_workflow_skill",
            "模块": "简历筛选",
            "所属 Agent": "Resume Screening Agent",
            "位置": "modules/resume_screening/scoring_engine.py::_SYSTEM_PROMPT",
            "用途": "基于岗位 JD、候选人画像和评分 Skill 做证据化评分。",
            "Prompt": _load_module_prompt("modules.resume_screening.scoring_engine", "_SYSTEM_PROMPT"),
        },
        {
            "名称": "面试题生成 Prompt",
            "Workflow Skill": "简历筛选 Workflow Skill",
            "Workflow Skill ID": "resume_screening_workflow_skill",
            "模块": "简历筛选",
            "所属 Agent": "Interview Question Agent",
            "位置": "modules/resume_screening/interview_gen.py::_SYSTEM_PROMPT",
            "用途": "根据候选人强项、短板和岗位要求生成追问问题。",
            "Prompt": _load_module_prompt("modules.resume_screening.interview_gen", "_SYSTEM_PROMPT"),
        },
        {
            "名称": "人才开源策略 Prompt",
            "Workflow Skill": "人才开源 Workflow Skill",
            "Workflow Skill ID": "talent_sourcing_workflow_skill",
            "模块": "人才开源",
            "所属 Agent": "Talent Sourcing Agent",
            "位置": "modules/talent_pool/sourcing.py::generate_sourcing_strategy",
            "用途": "根据人才画像生成关键词、数据源、搜索 Query 和风险提示。",
            "Prompt": """你是高端技术人才寻访专家。请基于以下需求生成公开人才寻访策略。
只返回 JSON，不要返回 Markdown。

要求：
- 搜索 query 默认围绕 GitHub、arXiv 生成；只有配置公司 People API 后才可使用公司人才库，Google Scholar 仅作为可选高级源。
- 不要建议绕过登录、验证码、权限墙。
- 强调候选人入库和联系必须人工确认。""",
        },
        {
            "名称": "候选线索抽取 Prompt",
            "Workflow Skill": "人才开源 Workflow Skill",
            "Workflow Skill ID": "talent_sourcing_workflow_skill",
            "模块": "人才开源",
            "所属 Agent": "Talent Sourcing Agent",
            "位置": "modules/talent_pool/sourcing.py::extract_candidate_leads",
            "用途": "从公开资料中抽取候选人线索、证据、风险和建议动作。",
            "Prompt": """你是高端技术人才寻访分析助手。请从公开资料中抽取可能匹配的人才线索。
只返回 JSON 数组，不要返回 Markdown。

规则：
- 只能基于公开资料下结论。
- 没有证据的字段写“未确认”。
- 推荐理由必须能被 evidence_links 或公开资料文本支撑。
- 不要输出私人电话、住址、身份证等敏感信息。""",
        },
        {
            "名称": "Skill 优化 Prompt",
            "Workflow Skill": "反馈调优 Workflow Skill",
            "Workflow Skill ID": "feedback_optimization_workflow_skill",
            "模块": "反馈追踪",
            "所属 Agent": "Feedback / Skill Optimization Agent",
            "位置": "app.py::_build_skill_optimization_prompt",
            "用途": "基于匿名化反馈样本分析误判规律，生成 HR 审核用优化建议。",
            "Prompt": "你是一名招聘评估体系优化专家，你的任务是基于匿名化招聘反馈样本，分析当前匹配 Skill 的误判规律，并生成可供 HR 审核的优化建议。",
        },
    ]


def _prompt_skill_files() -> list[Path]:
    prompt_dir = Path(__file__).resolve().parent / "skills" / "workflows"
    return sorted(prompt_dir.glob("*.md"))


def _prompt_skill_metadata(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta = {
        "skill_id": path.stem,
        "skill_name": path.stem,
        "module": "",
        "version": "",
        "prompt_count": "",
        "status": "",
    }
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip().strip('"')
    meta["path"] = path
    meta["content"] = text
    return meta


def _prompt_skill_registry(prompt_rows: list[dict]) -> list[dict]:
    by_id = {}
    for path in _prompt_skill_files():
        meta = _prompt_skill_metadata(path)
        by_id[meta["skill_id"]] = meta
    for row in prompt_rows:
        sid = row["Workflow Skill ID"]
        meta = by_id.setdefault(sid, {
            "skill_id": sid,
            "skill_name": row["Workflow Skill"],
            "module": row["模块"],
            "version": "v1",
            "prompt_count": "",
            "status": "active",
            "path": None,
            "content": "",
        })
        meta.setdefault("runtime_prompts", [])
        meta["runtime_prompts"].append(row)
    return list(by_id.values())


def _skill_markdown_files() -> list[Path]:
    skill_dir = Path(__file__).resolve().parent / "skills" / "matching"
    return [
        path for path in sorted(skill_dir.glob("*.md"))
        if path.name.lower() != "readme.md"
    ]

def _screening_decision_key(candidate, job_profile_id=""):
    return "||".join([
        str(job_profile_id or ""),
        str(candidate.profile.source_file or ""),
        str(candidate.profile.candidate_name or ""),
    ])


def _record_screening_tier(candidate, jd, decision: str, talent_tier: str):
    decision_key = _screening_decision_key(candidate, st.session_state.last_screening_profile_id)
    st.session_state.screening_decisions[decision_key] = {
        "decision": decision,
        "talent_tier": talent_tier,
        "reason": "",
        "ai_recommendation": candidate.hire_recommendation.value,
        "ai_score": round(candidate.weighted_total, 2),
        "candidate_name": candidate.profile.candidate_name,
        "source_file": candidate.profile.source_file,
        "job_profile_id": st.session_state.last_screening_profile_id,
        "updated_at": datetime.now().isoformat(),
    }
    followup_id, created = add_candidate_followup(
        candidate,
        jd,
        job_profile_id=st.session_state.last_screening_profile_id,
        department=st.session_state.last_screening_department,
        hr_screening_decision=decision,
        talent_tier=talent_tier,
    )
    action = "已加入" if created else "已更新"
    st.session_state.pending_screening_success = (
        f"{candidate.profile.candidate_name} 已标记为“{decision} · {talent_tier}”，"
        f"并{action}待反馈列表 #{followup_id}。"
    )

def _plotly_dark(fig, height=360):
    fig.update_layout(
        paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
        font=dict(family="Inter, sans-serif", size=11, color="#718078"),
        colorway=["#36c873", "#4f8ff7", "#8b5cf6", "#d4a72c", "#69d59a", "#78a8f8"],
        legend=dict(bgcolor="#ffffff", bordercolor="#e4ebe5",
                    borderwidth=1, font=dict(size=11, color="#718078")),
        margin=dict(t=30, b=40, l=40, r=20),
        height=height,
    )
    fig.update_xaxes(gridcolor="#edf2ee", linecolor="#d5dfd7",
                     tickfont=dict(color="#718078", size=10),
                     title_font=dict(color="#98a49d", size=10))
    fig.update_yaxes(gridcolor="#edf2ee", linecolor="#d5dfd7",
                     tickfont=dict(color="#718078", size=10),
                     title_font=dict(color="#98a49d", size=10))
    return fig

def _read_uploaded_table(uploaded_file, max_rows=80):
    if not uploaded_file:
        return [], ""
    data = uploaded_file.getvalue()
    suffix = Path(uploaded_file.name).suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(io.BytesIO(data))
        elif suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(io.BytesIO(data))
        else:
            return [], "Only CSV / Excel files are supported."
    except Exception as e:
        return [], f"Could not read {uploaded_file.name}: {e}"

    df = df.head(max_rows).fillna("")
    return df.to_dict(orient="records"), ""

def _sourcing_draft_path() -> Path:
    path = Path(__file__).resolve().parent / "data" / "sourcing_form_draft.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path

def _load_sourcing_form_draft() -> dict:
    path = _sourcing_draft_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_sourcing_form_draft() -> None:
    keys = [
        "src_creation_mode",
        "src_source_job_profile",
        "src_task_name",
        "src_direction",
        "src_level",
        "src_scene",
        "src_signals",
        "src_exclusions",
        "src_location",
        "src_linked_profile",
        "src_description",
    ]
    draft = {key: st.session_state.get(key) for key in keys if key in st.session_state}
    try:
        _sourcing_draft_path().write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning("Could not persist sourcing form draft: %s", e)

def _init_sourcing_form_draft(profile_options: list[str]) -> None:
    draft = _load_sourcing_form_draft()
    defaults = {
        "src_creation_mode": "手动输入",
        "src_source_job_profile": profile_options[1] if len(profile_options) > 1 else "",
        "src_task_name": "",
        "src_direction": "大模型",
        "src_level": "资深工程师",
        "src_scene": "",
        "src_signals": ["开源项目", "工程落地经验"],
        "src_exclusions": "",
        "src_location": "",
        "src_linked_profile": "不关联岗位",
        "src_description": "",
    }
    direction_options = ["大模型", "推荐算法", "搜索算法", "广告算法", "CV", "NLP", "多模态", "数据科学", "其他"]
    level_options = ["资深工程师", "专家", "技术负责人", "科研型人才", "潜力人才"]
    signal_options = ["顶会论文", "开源项目", "大厂经历", "技术博客", "专利", "公开演讲", "团队管理经验", "工程落地经验"]

    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = draft.get(key, default)

    if st.session_state.src_direction not in direction_options:
        st.session_state.src_direction = defaults["src_direction"]
    if st.session_state.src_level not in level_options:
        st.session_state.src_level = defaults["src_level"]
    st.session_state.src_signals = [
        signal for signal in st.session_state.get("src_signals", defaults["src_signals"])
        if signal in signal_options
    ] or defaults["src_signals"]
    if st.session_state.src_linked_profile not in profile_options:
        st.session_state.src_linked_profile = "不关联岗位"
    confirmed_profile_ids = profile_options[1:]
    if confirmed_profile_ids and st.session_state.src_source_job_profile not in confirmed_profile_ids:
        st.session_state.src_source_job_profile = confirmed_profile_ids[0]


def _infer_sourcing_direction(profile: dict) -> str:
    pkg = profile.get("package")
    internal = pkg.internal_profile if pkg else {}
    snapshot = profile.get("input_snapshot") or {}
    text = " ".join([
        str(profile.get("title", "")),
        str(snapshot.get("tech_stack", "")),
        " ".join(internal.get("must_have_skills", []) or []),
        " ".join(internal.get("nice_to_have_skills", []) or []),
    ]).lower()
    rules = [
        ("多模态", ["多模态", "multimodal"]),
        ("推荐算法", ["推荐系统", "推荐算法"]),
        ("搜索算法", ["搜索算法", "搜索排序"]),
        ("广告算法", ["广告算法", "广告排序"]),
        ("CV", ["计算机视觉", "computer vision", "视频生成", "diffusion"]),
        ("NLP", ["nlp", "自然语言处理"]),
        ("大模型", ["大模型", "llm", "agent", "rag"]),
        ("数据科学", ["数据科学", "data science", "数据挖掘"]),
    ]
    for direction, keywords in rules:
        if any(keyword in text for keyword in keywords):
            return direction
    return "其他"


def _load_sourcing_fields_from_job_profile(profile_id: str) -> None:
    profile = st.session_state.confirmed_job_profiles.get(profile_id)
    if not profile:
        return
    pkg = profile.get("package")
    internal = pkg.internal_profile if pkg else {}
    snapshot = profile.get("input_snapshot") or {}
    title = profile.get("title") or internal.get("job_title") or profile_id
    recruitment_type = snapshot.get("recruitment_type", "")
    job_level = snapshot.get("job_level", "")
    if recruitment_type == "校招" or "实习" in title:
        target_level = "潜力人才"
    elif "专家" in job_level:
        target_level = "专家"
    elif any(level in job_level for level in ["高级", "资深"]):
        target_level = "资深工程师"
    else:
        target_level = "资深工程师"

    searchable_text = " ".join(
        (internal.get("nice_to_have_skills", []) or [])
        + (internal.get("must_have_skills", []) or [])
    ).lower()
    signals = ["工程落地经验"]
    if any(word in searchable_text for word in ["开源", "github"]):
        signals.append("开源项目")
    if any(word in searchable_text for word in ["论文", "顶会", "cvpr", "icml", "neurips"]):
        signals.append("顶会论文")
    if "专利" in searchable_text:
        signals.append("专利")

    st.session_state.src_task_name = f"{title}人才寻访"
    st.session_state.src_direction = _infer_sourcing_direction(profile)
    st.session_state.src_level = target_level
    st.session_state.src_scene = (
        internal.get("business_context")
        or snapshot.get("business_background")
        or f"{title}岗位人才寻访"
    )
    st.session_state.src_signals = list(dict.fromkeys(signals))
    st.session_state.src_exclusions = "；".join(internal.get("negative_signals", []) or [])
    st.session_state.src_location = snapshot.get("location", "")
    st.session_state.src_linked_profile = profile_id
    st.session_state.src_description = pkg.public_jd if pkg else ""
    _save_sourcing_form_draft()

# ── CONSTANTS ──────────────────────────────────────────────────────────────────
DIMENSION_LABELS = {
    "hard_skills_match":        ("Hard skills",          "30%"),
    "business_project_match":   ("Business/projects",    "25%"),
    "seniority_level_match":    ("Seniority/level",      "15%"),
    "education_school_match":   ("Education/school",     "10%"),
    "soft_requirements_match":  ("Soft requirements",    "10%"),
    "risk_signal_control":      ("Low-risk signal",      "10%"),
}
DIM_SHORT   = ["Skills","Business","Level","Education","Soft","Risk"]
BADGE_COLOR = {"Strong Hire":"green","Hire":"blue","Maybe":"amber","No Hire":"red"}

# ── SESSION STATE ──────────────────────────────────────────────────────────────
_defaults = {
    "parsed_jd": None, "ranked": None, "run_complete": False,
    "interview_cache": {},
    "seed_triggered": False, "generated_jd_package": None,
    "job_profiles": {}, "selected_job_profile_id": None,
    "jd_drafts": {}, "confirmed_job_profiles": {},
    "selected_confirmed_profile_id": None,
    "last_screening_profile_id": "",
    "last_screening_department": "",
    "screening_decisions": {},
    "pending_screening_success": "",
    "quick_generate_requested": False, "inferred_jd_fields": None,
    "matching_skill_configs": None,
}
for k,v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

if st.session_state.matching_skill_configs is None:
    st.session_state.matching_skill_configs = {
        skill_id: json.loads(json.dumps(config, ensure_ascii=False))
        for skill_id, config in MATCHING_SKILLS.items()
    }

_JOB_PROFILE_STORE = Path(__file__).parent / "data" / "job_profiles_store.json"


def _package_to_dict(pkg):
    if pkg is None:
        return None
    if hasattr(pkg, "model_dump"):
        return pkg.model_dump()
    if hasattr(pkg, "dict"):
        return pkg.dict()
    return pkg


def _serialize_profile_store(collection: dict) -> dict:
    serialized = {}
    for profile_id, profile in (collection or {}).items():
        item = dict(profile)
        item["package"] = _package_to_dict(item.get("package"))
        serialized[profile_id] = item
    return serialized


def _deserialize_profile_store(collection: dict) -> dict:
    restored = {}
    for profile_id, profile in (collection or {}).items():
        item = dict(profile)
        pkg_data = item.get("package")
        if isinstance(pkg_data, dict):
            try:
                item["package"] = GeneratedJD(**pkg_data)
            except Exception:
                item["package"] = GeneratedJD(
                    public_jd=str(pkg_data.get("public_jd", "")),
                    internal_profile=pkg_data.get("internal_profile", {}) or {},
                    screening_strategy=pkg_data.get("screening_strategy", []) or [],
                    scoring_weights=pkg_data.get("scoring_weights", {}) or {},
                    interview_focus=pkg_data.get("interview_focus", []) or [],
                )
        restored[profile_id] = item
    return restored


def _load_job_profile_store() -> dict:
    if not _JOB_PROFILE_STORE.exists():
        return {}
    try:
        return json.loads(_JOB_PROFILE_STORE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _persist_job_profile_store() -> None:
    _JOB_PROFILE_STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "jd_drafts": _serialize_profile_store(st.session_state.jd_drafts),
        "confirmed_job_profiles": _serialize_profile_store(st.session_state.confirmed_job_profiles),
        "selected_confirmed_profile_id": st.session_state.selected_confirmed_profile_id,
        "updated_at": datetime.now().isoformat(),
    }
    _JOB_PROFILE_STORE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _restore_or_persist_job_profiles() -> None:
    has_session_profiles = bool(st.session_state.jd_drafts or st.session_state.confirmed_job_profiles)
    store = _load_job_profile_store()
    if not has_session_profiles and store:
        st.session_state.jd_drafts = _deserialize_profile_store(store.get("jd_drafts", {}))
        st.session_state.confirmed_job_profiles = _deserialize_profile_store(store.get("confirmed_job_profiles", {}))
        st.session_state.job_profiles = dict(st.session_state.confirmed_job_profiles)
        selected_id = store.get("selected_confirmed_profile_id")
        if selected_id in st.session_state.confirmed_job_profiles:
            st.session_state.selected_confirmed_profile_id = selected_id
    elif has_session_profiles:
        st.session_state.job_profiles = dict(st.session_state.confirmed_job_profiles)
        _persist_job_profile_store()


_restore_or_persist_job_profiles()


def active_matching_skill_by_id(skill_id) -> dict:
    if skill_id in st.session_state.matching_skill_configs:
        return json.loads(json.dumps(st.session_state.matching_skill_configs[skill_id], ensure_ascii=False))
    return get_matching_skill_by_id(skill_id)


def active_matching_skill(job_family, hiring_type) -> dict:
    base_skill = get_matching_skill(job_family, hiring_type)
    return active_matching_skill_by_id(base_skill["skill_id"])


def sync_matching_skill_to_profiles(skill: dict) -> None:
    skill_id = skill["skill_id"]
    for collection_name in ("jd_drafts", "confirmed_job_profiles", "job_profiles"):
        collection = st.session_state.get(collection_name, {})
        for profile in collection.values():
            if profile.get("matching_skill_id") == skill_id:
                profile["matching_skill"] = json.loads(json.dumps(skill, ensure_ascii=False))
    _persist_job_profile_store()


def sidebar_jump(module_name: str, **state_updates) -> None:
    st.session_state["active_page"] = module_name
    if module_name in {"JD 生成", "简历筛选", "人才开源"}:
        st.session_state["main_module_nav"] = module_name
        st.session_state["last_main_module_nav"] = module_name
    for key, value in state_updates.items():
        st.session_state[key] = value

# ── SIDEBAR ────────────────────────────────────────────────────────────────────
if "active_page" not in st.session_state:
    st.session_state["active_page"] = st.session_state.get("main_module_nav", "JD 生成")
if "last_main_module_nav" not in st.session_state:
    st.session_state["last_main_module_nav"] = st.session_state.get("main_module_nav", "JD 生成")

with st.sidebar:
    st.markdown("""
    <div class="side-brand">
      <div class="side-brand-row">
        <div class="side-logo">T</div>
        <div>
          <div class="side-title">TalentOS</div>
          <div class="side-sub">人才运营智能平台</div>
        </div>
      </div>
    </div>
    <div class="side-nav-group">核心功能</div>
    """, unsafe_allow_html=True)
    main_module = st.radio(
        "核心功能",
        ["JD 生成", "简历筛选", "人才开源"],
        index=0,
        key="main_module_nav",
        label_visibility="collapsed",
    )
    if main_module != st.session_state.get("last_main_module_nav"):
        st.session_state["active_page"] = main_module
        st.session_state["last_main_module_nav"] = main_module
    st.markdown("""
    <div class="side-nav-group">管理工具</div>
    """, unsafe_allow_html=True)
    if st.button(
        "库  岗位库",
        key="sidebar_job_library",
        use_container_width=True,
        on_click=sidebar_jump,
        args=("岗位库",),
    ):
        pass
    if st.button(
        "人  人才库",
        key="sidebar_talent_library",
        use_container_width=True,
        on_click=sidebar_jump,
        args=("人才库",),
    ):
        pass
    if st.button(
        "馈  反馈追踪",
        key="sidebar_feedback_tracking",
        use_container_width=True,
        on_click=sidebar_jump,
        args=("反馈追踪",),
        kwargs={"pending_followup_status_filter": "全部"},
    ):
        pass
    if st.button(
        "规  Workflow / Matching",
        key="sidebar_prompt_skill",
        use_container_width=True,
        on_click=sidebar_jump,
        args=("Workflow / Matching",),
    ):
        pass

    st.divider()
    section_label("AI provider")
    provider_options = ["Groq", "MiniMax"]
    current_provider = os.environ.get("LLM_PROVIDER", "groq").strip().lower()
    provider_index = 1 if current_provider == "minimax" else 0
    provider_choice = st.selectbox(
        "AI Provider",
        provider_options,
        index=provider_index,
        help="Choose which online LLM provider powers JD parsing, resume parsing, scoring, and interview questions.",
    )
    os.environ["LLM_PROVIDER"] = provider_choice.lower()

    if provider_choice == "Groq":
        groq_key = st.text_input(
            "Groq API key",
            type="password",
            value=os.environ.get("GROQ_API_KEY", ""),
            placeholder="gsk_...",
            help="Get one at https://console.groq.com/keys",
        )
        groq_model = st.text_input(
            "Groq model",
            value=os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL),
            help="Default: llama-3.3-70b-versatile",
        )
        if groq_key:
            os.environ["GROQ_API_KEY"] = groq_key
        if groq_model:
            os.environ["GROQ_MODEL"] = groq_model
    else:
        minimax_key = st.text_input(
            "MiniMax API key",
            type="password",
            value=os.environ.get("MINIMAX_API_KEY", ""),
            placeholder="MiniMax API key...",
            help="Get one from your MiniMax developer console.",
        )
        minimax_model = st.text_input(
            "MiniMax model",
            value=os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL),
            help="Default: MiniMax-M3. Override if your MiniMax account uses another model name.",
        )
        anthropic_base_url = st.text_input(
            "Anthropic base URL",
            value=os.environ.get("ANTHROPIC_BASE_URL", "https://api.minimaxi.com/anthropic"),
            help="MiniMax Anthropic-compatible endpoint.",
        )
        if minimax_key:
            os.environ["MINIMAX_API_KEY"] = minimax_key
        if minimax_model:
            os.environ["MINIMAX_MODEL"] = minimax_model
        if anthropic_base_url:
            os.environ["ANTHROPIC_BASE_URL"] = anthropic_base_url

    ls_key = st.text_input("LangSmith key", type="password",
        value=os.environ.get("LANGCHAIN_API_KEY",""), placeholder="Optional — tracing")
    if ls_key:
        os.environ["LANGCHAIN_API_KEY"] = ls_key
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = "talentos-hr-agent"

    st.divider()
    section_label("Demo data")
    if st.button("🪄 Generate sample data", use_container_width=True,
                 help="Seeds 150 screening records and 40 talent pool entries for analytics preview"):
        msg = seed_demo_data(force=False)
        st.success(msg)
        st.session_state.seed_triggered = True

    section_label("System")
    embedding_label = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    if os.environ.get("ENABLE_EMBEDDING_SIGNAL", "true").strip().lower() in {"0", "false", "no", "off"}:
        embedding_label = "Embeddings disabled"
    st.markdown(f"""
    <div style="display:flex;flex-direction:column;gap:7px">
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#718078">
        <div style="width:6px;height:6px;border-radius:50%;background:#69c987;box-shadow:0 0 10px rgba(105,201,135,0.6);flex-shrink:0"></div>{provider_label()}</div>
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#718078">
        <div style="width:6px;height:6px;border-radius:50%;background:#9bdc78;box-shadow:0 0 10px rgba(155,220,120,0.55);flex-shrink:0"></div>{embedding_label}</div>
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#718078">
        <div style="width:6px;height:6px;border-radius:50%;background:#8b5cf6;box-shadow:0 0 10px rgba(139,92,246,0.55);flex-shrink:0"></div>Pydantic v2 validation</div>
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#718078">
        <div style="width:6px;height:6px;border-radius:50%;background:#69c987;box-shadow:0 0 10px rgba(105,201,135,0.6);flex-shrink:0"></div>SQLite persistence · <span style="font-family:JetBrains Mono,monospace;color:#98a49d">{get_db_path()}</span>
      </div>
    </div>""", unsafe_allow_html=True)

active_page = st.session_state.get("active_page", main_module)
page_titlebar(active_page)

if active_page in {"Workflow / Matching", "Prompt / Skill"}:
    prompt_rows = _runtime_prompt_registry()
    prompt_skill_rows = _prompt_skill_registry(prompt_rows)
    runtime_tab, skill_tab = st.tabs(["业务 Workflow Skill", "评分 Matching Skill"])

    with runtime_tab:
        st.markdown("""
        <div class="tp-card">
          <div class="tp-card-title">业务 Workflow Skill 分组总览</div>
          <div class="tp-card-headline">9 个运行时 Prompt 已按三个核心功能模块和反馈调优闭环组织成 4 个 Workflow Skill。Workflow 管调用链路，Matching 管评分规则。</div>
        </div>
        """, unsafe_allow_html=True)
        r1, r2, r3 = st.columns(3)
        r1.metric("Workflow Skill", len(prompt_skill_rows))
        r2.metric("运行时 Prompt", len(prompt_rows))
        r3.metric("修改方式", "人工确认")

        st.dataframe(
            pd.DataFrame([
                {
                    "Workflow Skill": row["skill_name"],
                    "Skill ID": row["skill_id"],
                    "业务模块": row.get("module", ""),
                    "版本": row.get("version", ""),
                    "包含 Prompt": len(row.get("runtime_prompts", [])),
                    "文档": str(row["path"].relative_to(Path(__file__).resolve().parent)) if row.get("path") else "未找到",
                    "状态": row.get("status", ""),
                }
                for row in prompt_skill_rows
            ]),
            use_container_width=True,
            hide_index=True,
        )

        selected_prompt_skill_name = st.selectbox(
            "查看业务 Workflow Skill",
            [row["skill_name"] for row in prompt_skill_rows],
            key="prompt_library_selected_prompt_skill",
        )
        selected_prompt_skill = next(
            row for row in prompt_skill_rows
            if row["skill_name"] == selected_prompt_skill_name
        )

        c1, c2 = st.columns([0.44, 0.56], gap="large")
        with c1:
            st.markdown("##### 组内 Prompt 调用映射")
            grouped_prompts = selected_prompt_skill.get("runtime_prompts", [])
            st.dataframe(
                pd.DataFrame([
                    {
                        "Prompt": row["名称"],
                        "Agent": row["所属 Agent"],
                        "用途": row["用途"],
                        "位置": row["位置"],
                    }
                    for row in grouped_prompts
                ]),
                use_container_width=True,
                hide_index=True,
            )

            if grouped_prompts:
                selected_prompt_name = st.selectbox(
                    "查看组内 Prompt 内容",
                    [row["名称"] for row in grouped_prompts],
                    key=f"prompt_library_group_prompt_{selected_prompt_skill['skill_id']}",
                )
                selected_prompt = next(row for row in grouped_prompts if row["名称"] == selected_prompt_name)
                st.caption(selected_prompt["位置"])
                st.text_area(
                    "运行时 Prompt 内容",
                    value=selected_prompt["Prompt"],
                    height=320,
                    key=f"prompt_view_{selected_prompt_skill['skill_id']}_{selected_prompt_name}",
                    disabled=True,
                )
        with c2:
            st.markdown("##### Workflow Skill 文档")
            if selected_prompt_skill.get("path"):
                st.caption(str(selected_prompt_skill["path"].relative_to(Path(__file__).resolve().parent)))
            st.text_area(
                "Markdown 原文",
                value=selected_prompt_skill.get("content", ""),
                height=560,
                key=f"prompt_skill_markdown_{selected_prompt_skill['skill_id']}",
                disabled=True,
            )

    with skill_tab:
        skill_files = _skill_markdown_files()
        st.markdown("""
        <div class="tp-card">
          <div class="tp-card-title">Markdown Skill 文档</div>
          <div class="tp-card-headline">评分 Skill 是 HR 可审阅的自然语言规则，包含权重、硬性检查、正负向信号、证据规则和面试关注点。</div>
        </div>
        """, unsafe_allow_html=True)
        s1, s2, s3 = st.columns(3)
        s1.metric("Skill 文档", len(skill_files))
        s2.metric("已加载 Skill", len(MATCHING_SKILLS))
        s3.metric("当前策略", "人工确认后修改")

        if not skill_files:
            st.warning("没有找到 Markdown Skill 文档。")
        else:
            skill_file_names = [path.name for path in skill_files]
            selected_skill_file_name = st.selectbox(
                "查看 Skill 文档",
                skill_file_names,
                key="prompt_library_selected_skill_file",
            )
            selected_skill_path = next(path for path in skill_files if path.name == selected_skill_file_name)
            skill_text = selected_skill_path.read_text(encoding="utf-8")
            skill_id = selected_skill_path.stem
            loaded_skill = MATCHING_SKILLS.get(skill_id, {})

            c1, c2 = st.columns([0.42, 0.58], gap="large")
            with c1:
                st.markdown("##### Skill 元信息")
                if loaded_skill:
                    st.json({
                        "skill_id": loaded_skill.get("skill_id"),
                        "skill_name": loaded_skill.get("skill_name"),
                        "job_family": loaded_skill.get("job_family"),
                        "hiring_type": loaded_skill.get("hiring_type"),
                        "version": loaded_skill.get("version"),
                        "focus_summary": loaded_skill.get("focus_summary"),
                    })
                    if loaded_skill.get("dimension_weights"):
                        st.markdown("##### 评分权重")
                        weight_rows = [
                            {"维度": key, "权重": value}
                            for key, value in loaded_skill.get("dimension_weights", {}).items()
                        ]
                        st.dataframe(pd.DataFrame(weight_rows), use_container_width=True, hide_index=True)
                else:
                    st.info("这份 Markdown 文档未被当前 Skill loader 加载。")
            with c2:
                st.markdown("##### Markdown 原文")
                st.caption(str(selected_skill_path.relative_to(Path(__file__).resolve().parent)))
                st.text_area(
                    "Skill Markdown",
                    value=skill_text,
                    height=520,
                    key=f"skill_markdown_view_{selected_skill_file_name}",
                    disabled=True,
                )

if active_page == "岗位库":
    confirmed_profiles = st.session_state.confirmed_job_profiles
    st.markdown("""
    <div class="tp-card">
      <div class="tp-card-title">岗位库只保存已确认 JD</div>
      <div class="tp-card-headline">待确认草稿不会进入岗位库；这里的岗位可被“简历筛选”和“人才开源”调用。</div>
    </div>
    """, unsafe_allow_html=True)
    k1, k2, k3 = st.columns(3)
    k1.metric("已确认岗位", len(confirmed_profiles))
    k2.metric("待确认草稿", len(st.session_state.jd_drafts))
    active_skill_count = len({
        profile.get("matching_skill_id", "")
        for profile in confirmed_profiles.values()
        if profile.get("matching_skill_id")
    })
    k3.metric("绑定 Skill", active_skill_count)

    if not confirmed_profiles:
        st.info("暂无已确认岗位。请先到“JD 生成”生成 JD 草稿，并点击确认创建岗位。")
        if st.button("去新建岗位", type="primary", use_container_width=True):
            sidebar_jump("JD 生成")
            st.rerun()
    else:
        rows = []
        for profile_id, profile in confirmed_profiles.items():
            snapshot = profile.get("input_snapshot", {}) or {}
            skill = profile.get("matching_skill", {}) or {}
            rows.append({
                "岗位 ID": profile_id,
                "岗位名称": snapshot.get("job_title", profile_id),
                "部门": snapshot.get("department", ""),
                "招聘类型": snapshot.get("recruitment_type", ""),
                "岗位序列": snapshot.get("job_family", ""),
                "版本": profile.get("version", "v1"),
                "状态": profile.get("status", "confirmed"),
                "绑定 Skill": skill.get("skill_name", profile.get("matching_skill_id", "")),
                "确认时间": profile.get("confirmed_at", ""),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        selected_profile_id = st.selectbox("查看岗位详情", list(confirmed_profiles.keys()), key="job_library_selected_profile")
        selected_profile = confirmed_profiles[selected_profile_id]
        selected_pkg = selected_profile["package"]
        c1, c2 = st.columns([1.15, 0.85], gap="large")
        with c1:
            st.markdown("##### 已确认 JD")
            st.text_area("JD 正文", value=selected_pkg.public_jd, height=320, key=f"job_library_jd_{selected_profile_id}")
        with c2:
            st.markdown("##### 岗位画像与调用")
            st.json(selected_pkg.internal_profile)
            selected_skill = selected_profile.get("matching_skill", {}) or {}
            st.markdown("**绑定评分 Skill**")
            st.caption(selected_skill.get("skill_name", selected_profile.get("matching_skill_id", "未绑定")))
            b1, b2 = st.columns(2)
            with b1:
                if st.button("用于简历筛选", use_container_width=True, key=f"use_job_screening_{selected_profile_id}"):
                    st.session_state.selected_confirmed_profile_id = selected_profile_id
                    sidebar_jump("简历筛选")
                    st.rerun()
            with b2:
                if st.button("用于人才开源", use_container_width=True, key=f"use_job_sourcing_{selected_profile_id}"):
                    st.session_state.src_creation_mode = "从已有岗位 JD 创建"
                    st.session_state.src_source_job_profile = selected_profile_id
                    st.session_state.src_linked_profile = selected_profile_id
                    sidebar_jump("人才开源", sourcing_sub_view="1. 开源寻访画像")
                    st.rerun()

if active_page == "人才库":
    pool_stats = talent_stats()
    st.markdown("""
    <div class="tp-card">
      <div class="tp-card-title">人才库分为内部与外部两类</div>
      <div class="tp-card-headline">内部人才库来自未来接入的 People API；外部人才库只保存你在人才开源中人工确认加入的人。</div>
    </div>
    """, unsafe_allow_html=True)
    t1, t2, t3 = st.columns(3)
    t1.metric("内部 People API", "已接入" if people_system_enabled() else "未接入")
    t2.metric("外部入库人才", pool_stats["total"])
    t3.metric("活跃人才", pool_stats["active"])

    internal_tab, external_tab = st.tabs(["内部人才库", "外部人才库"])
    with internal_tab:
        if not people_system_enabled():
            st.info("公司 People API 尚未接入。接入后这里会展示内部人才库，不读取本地演示数据冒充公司人才。")
            st.markdown("""
            <div class="method-card">
              <div class="method-card-title">预留 API 能力</div>
              <div class="method-card-sub">搜索人才、读取人才详情、查询候选流程状态、按授权导入本地候选快照。</div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.success("People API 已配置。后续可在这里接入搜索、详情和状态查询。")
            st.caption("为避免误触真实内部系统，本页先展示接入状态；正式字段映射完成后再开放查询。")

    with external_tab:
        section_label("外部人才检索")
        f1, f2, f3 = st.columns([2, 1, 1])
        with f1:
            pool_kw = st.text_input("关键词", placeholder="姓名、技能、项目、方向", key="management_pool_kw")
        with f2:
            pool_skill = st.text_input("技能", placeholder="Python / LLM", key="management_pool_skill")
        with f3:
            min_years = st.number_input("最低经验年限", min_value=0.0, max_value=30.0, value=0.0, step=1.0, key="management_pool_min_years")
        external_results = search_talents(
            keyword=pool_kw or None,
            min_experience=min_years if min_years > 0 else None,
            skill=pool_skill or None,
            limit=300,
        )
        if not external_results:
            st.info("暂无外部入库人才。请先在“人才开源”中确认候选人加入人才库。")
        else:
            pool_rows = []
            for rec in external_results:
                pool_rows.append({
                    "ID": rec.id,
                    "候选人": rec.candidate_name,
                    "方向": rec.domain,
                    "级别": rec.seniority_level,
                    "经验": rec.total_experience_years,
                    "地点": rec.location,
                    "状态": rec.status.value,
                    "技能": "、".join(rec.skills[:6]),
                    "更新时间": rec.updated_at.strftime("%Y-%m-%d") if rec.updated_at else "",
                })
            st.dataframe(pd.DataFrame(pool_rows), use_container_width=True, hide_index=True)
            selected_talent_id = st.selectbox(
                "查看外部人才详情",
                [rec.id for rec in external_results],
                format_func=lambda rid: next((r.candidate_name for r in external_results if r.id == rid), f"#{rid}"),
                key="management_pool_selected",
            )
            selected_talent = next((r for r in external_results if r.id == selected_talent_id), None)
            if selected_talent:
                d1, d2 = st.columns([1, 1], gap="large")
                with d1:
                    st.markdown("##### 人才摘要")
                    st.write(selected_talent.work_summary or "暂无工作摘要。")
                    st.write(selected_talent.project_summary or "暂无项目摘要。")
                with d2:
                    st.markdown("##### 标签与证据")
                    st.markdown(_skill_tags(selected_talent.skills, max_show=16), unsafe_allow_html=True)
                    if selected_talent.raw_profile:
                        with st.expander("查看原始入库快照"):
                            try:
                                st.json(json.loads(selected_talent.raw_profile))
                            except Exception:
                                st.text(selected_talent.raw_profile)

if active_page == "反馈追踪":
    pending_followup_filter = st.session_state.pop("pending_followup_status_filter", None)
    if pending_followup_filter in {"待反馈", "已反馈", "全部"}:
        st.session_state["management_followup_status_filter"] = pending_followup_filter

    followup_stats = candidate_followup_stats()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("待反馈", followup_stats.get("待反馈", 0))
    m2.metric("已反馈", followup_stats.get("已反馈", 0))
    m3.metric("全部记录", followup_stats.get("total", 0))
    all_followups_for_management = list_candidate_followups(status=None, limit=1000)
    valid_followups_all = [
        item for item in all_followups_for_management
        if _is_valid_optimization_sample(item)
    ]
    m4.metric("有效调优样本", len(valid_followups_all))

    st.markdown("""
    <div class="tp-card">
      <div class="tp-card-title">Skill 调优规则</div>
      <div class="tp-card-headline">每个 Skill 累计 20 条有效反馈后，可生成优化建议；AI 只提供建议和拟修改 diff，最终是否写入由你确认。</div>
    </div>
    """, unsafe_allow_html=True)

    skill_summary_rows = _feedback_skill_summary(all_followups_for_management)
    if skill_summary_rows:
        with st.expander("Skill 样本统计", expanded=True):
            st.dataframe(pd.DataFrame(skill_summary_rows), use_container_width=True, hide_index=True)

    skill_counts = {
        sid: {"name": skill.get("skill_name", sid), "count": 0}
        for sid, skill in st.session_state.matching_skill_configs.items()
    }
    for item in valid_followups_all:
        sid = item.get("matching_skill_id") or "unknown"
        skill_counts.setdefault(sid, {"name": item.get("matching_skill_name") or sid, "count": 0})
        skill_counts[sid]["count"] += 1
    for sid, payload in skill_counts.items():
        progress = min(payload["count"] / 20, 1.0)
        c1, c2 = st.columns([3, 1])
        with c1:
            st.markdown(f"**{payload['name']}** · {payload['count']}/20 条有效反馈")
            st.progress(progress)
        with c2:
            ready = payload["count"] >= 20
            if st.button(
                "生成优化建议",
                disabled=not ready,
                use_container_width=True,
                key=f"generate_skill_opt_{sid}",
            ):
                selected_skill = active_matching_skill_by_id(sid)
                skill_samples = [
                    item for item in valid_followups_all
                    if (item.get("matching_skill_id") or "unknown") == sid
                ]
                with st.spinner("正在基于匿名化反馈样本生成优化建议草案..."):
                    report = _generate_skill_optimization_report(selected_skill, skill_samples)
                st.session_state["pending_skill_optimization"] = sid
                st.session_state["skill_optimization_report"] = report
                st.success("已生成优化建议草案。请在下方审核，确认前不会写入 Skill。")

    pending_report = st.session_state.get("skill_optimization_report")
    pending_skill_id = st.session_state.get("pending_skill_optimization")
    if pending_report and pending_skill_id:
        with st.container(border=True):
            st.markdown("##### Skill 优化建议草案")
            st.caption("这是基于匿名化反馈样本生成的建议，不会自动修改 Markdown Skill。")
            st.json(pending_report)
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("保留为待审核建议", use_container_width=True, key="keep_skill_report"):
                    st.success("已保留在当前会话中。后续可继续扩展为写入审核流。")
            with c2:
                if st.button("去 Skill 权重设置", use_container_width=True, key="go_skill_weight_from_report"):
                    sidebar_jump("JD 生成", pending_jd_workspace="评分 Skill 设置")
                    st.rerun()
            with c3:
                if st.button("清除草案", use_container_width=True, key="clear_skill_report"):
                    st.session_state.pop("skill_optimization_report", None)
                    st.session_state.pop("pending_skill_optimization", None)
                    st.rerun()

    section_label("反馈列表")
    f1, f2, f3, f4 = st.columns([1, 1, 1, 2])
    with f1:
        status_choice = st.radio(
            "反馈状态",
            ["待反馈", "已反馈", "全部"],
            horizontal=True,
            key="management_followup_status_filter",
        )
    with f2:
        skill_choice = st.selectbox(
            "Skill",
            ["全部"] + sorted({
                item.get("matching_skill_name") or item.get("matching_skill_id") or "未知"
                for item in list_candidate_followups(status=None, limit=1000)
            }),
            key="management_followup_skill_filter",
        )
    with f3:
        validity_choice = st.selectbox(
            "样本有效性",
            ["全部", "有效调优样本", "无效/待补充"],
            key="management_followup_validity_filter",
        )
    with f4:
        keyword_filter = st.text_input("搜索候选人 / 岗位 / 原因", key="management_followup_kw")

    status_filter = None if status_choice == "全部" else status_choice
    followups = list_candidate_followups(status=status_filter, limit=1000)
    if skill_choice != "全部":
        followups = [
            item for item in followups
            if (item.get("matching_skill_name") or item.get("matching_skill_id") or "未知") == skill_choice
        ]
    if validity_choice == "有效调优样本":
        followups = [item for item in followups if _is_valid_optimization_sample(item)]
    elif validity_choice == "无效/待补充":
        followups = [item for item in followups if not _is_valid_optimization_sample(item)]
    if keyword_filter.strip():
        kw = keyword_filter.strip().lower()
        followups = [
            item for item in followups
            if kw in " ".join([
                str(item.get("candidate_name", "")),
                str(item.get("job_title", "")),
                str(item.get("fail_reason", "")),
                str(item.get("hr_note", "")),
                str(item.get("final_result", "")),
            ]).lower()
        ]

    if not followups:
        st.info("当前筛选条件下暂无反馈记录。")
    else:
        feedback_rows = _feedback_export_rows(followups)
        tag_counts = {}
        for item in followups:
            for tag in _infer_feedback_tags(item):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        if tag_counts:
            top_tags = sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
            st.markdown("##### 高频反馈原因")
            st.markdown(
                _skill_tags([f"{tag} · {count}" for tag, count in top_tags], max_show=10),
                unsafe_allow_html=True,
            )
        st.dataframe(pd.DataFrame(feedback_rows), use_container_width=True, hide_index=True)
        csv_data = pd.DataFrame(feedback_rows).to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "下载反馈追踪 CSV",
            data=csv_data,
            file_name=f"candidate_feedback_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        selected_followup_id = st.selectbox(
            "查看反馈详情",
            [item["id"] for item in followups],
            format_func=lambda fid: next((f"#{item['id']} · {item['candidate_name']} · {item['job_title']}" for item in followups if item["id"] == fid), f"#{fid}"),
            key="management_selected_followup",
        )
        selected_followup = next((item for item in followups if item["id"] == selected_followup_id), None)
        if selected_followup:
            d1, d2 = st.columns([1, 1], gap="large")
            with d1:
                st.markdown("##### 初筛与反馈")
                st.json({
                    "candidate": selected_followup["candidate_name"],
                    "job": selected_followup["job_title"],
                    "skill": selected_followup["matching_skill_name"],
                    "initial_score": selected_followup["initial_score"],
                    "hr_decision": selected_followup.get("hr_screening_decision", ""),
                    "talent_tier": selected_followup.get("talent_tier", ""),
                    "final_result": selected_followup.get("final_result", ""),
                    "reason": selected_followup.get("fail_reason") or selected_followup.get("hr_note", ""),
                    "reason_tags": _infer_feedback_tags(selected_followup),
                    "sample_validity": "有效调优样本" if _is_valid_optimization_sample(selected_followup) else "待补充",
                    "misjudgment_type": _feedback_misjudgment_type(selected_followup),
                })
            with d2:
                st.markdown("##### 证据快照")
                with st.expander("查看当时评分证据", expanded=True):
                    st.json(selected_followup.get("score_snapshot", {}))
                if st.button("进入反馈填写页", use_container_width=True):
                    sidebar_jump("简历筛选", pending_followup_status_filter=selected_followup.get("current_status", "全部"))
                    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1: JD GENERATION & JOB PROFILES
# ═══════════════════════════════════════════════════════════════════════════════
if active_page == "JD 生成":
    confirmed_workspace_options = [
        f"岗位：{profile_id}" for profile_id in st.session_state.confirmed_job_profiles.keys()
    ]
    jd_workspace_options = ["新建岗位", "待确认草稿", "评分 Skill 设置"] + confirmed_workspace_options
    pending_workspace = st.session_state.pop("pending_jd_workspace", None)
    if pending_workspace in jd_workspace_options:
        st.session_state["jd_workspace"] = pending_workspace
    if st.session_state.get("jd_workspace") not in jd_workspace_options:
        st.session_state["jd_workspace"] = "新建岗位"
    jd_workspace = st.radio(
        "二级目录",
        jd_workspace_options,
        horizontal=True,
        key="jd_workspace",
    )
    c_draft, c_confirmed = st.columns(2, gap="medium")
    c_draft.metric("待确认草稿", len(st.session_state.jd_drafts))
    c_confirmed.metric("已确认岗位档案", len(st.session_state.confirmed_job_profiles))

    if jd_workspace == "评分 Skill 设置":
        st.markdown("#### 评分 Skill 权重设置")
        st.caption("修改后需要点击保存才会生效。权重总和必须等于 100%。")
        skill_ids = list(st.session_state.matching_skill_configs.keys())
        selected_skill_id = st.selectbox(
            "选择要编辑的评分 Skill",
            skill_ids,
            format_func=lambda sid: st.session_state.matching_skill_configs[sid]["skill_name"],
            key="editable_matching_skill_selector",
        )
        editable_skill = st.session_state.matching_skill_configs[selected_skill_id]
        st.info(f"{editable_skill['skill_name']} · {editable_skill['focus_summary']}")

        with st.form(f"matching_skill_weight_form_{selected_skill_id}"):
            st.markdown("##### 维度权重")
            edited_percentages = {}
            weight_cols = st.columns(2, gap="medium")
            for idx, dim_key in enumerate(DIMENSION_KEYS):
                label = editable_skill.get("dimension_labels", {}).get(dim_key, DIMENSION_LABELS[dim_key][0])
                current_pct = float(editable_skill["dimension_weights"].get(dim_key, 0)) * 100
                with weight_cols[idx % 2]:
                    edited_percentages[dim_key] = st.number_input(
                        label,
                        min_value=0.0,
                        max_value=100.0,
                        value=round(current_pct, 1),
                        step=1.0,
                        key=f"skill_weight_{selected_skill_id}_{dim_key}",
                    )

            total_pct = round(sum(edited_percentages.values()), 1)
            st.metric("当前权重总和", f"{total_pct:.1f}%")
            st.markdown("##### 当前规则说明")
            st.json({
                "hard_checks": editable_skill.get("hard_checks", []),
                "positive_signals": editable_skill.get("positive_signals", []),
                "negative_signals": editable_skill.get("negative_signals", []),
                "interview_focus": editable_skill.get("interview_focus", []),
            })
            save_skill_weights = st.form_submit_button("保存权重配置", type="primary", use_container_width=True)

        reset_col, note_col = st.columns([1, 2], gap="medium")
        with reset_col:
            reset_skill_weights = st.button("恢复该 Skill 默认权重", use_container_width=True, key=f"reset_{selected_skill_id}")
        with note_col:
            st.caption("保存后会同步更新当前会话中引用该 Skill 的待确认草稿和已确认岗位。")

        if save_skill_weights:
            if abs(total_pct - 100.0) > 0.01:
                st.error("权重总和必须等于 100%，请调整后再保存。")
            else:
                updated_skill = json.loads(json.dumps(editable_skill, ensure_ascii=False))
                updated_skill["dimension_weights"] = {
                    dim_key: round(edited_percentages[dim_key] / 100, 4)
                    for dim_key in DIMENSION_KEYS
                }
                st.session_state.matching_skill_configs[selected_skill_id] = updated_skill
                sync_matching_skill_to_profiles(updated_skill)
                st.success(f"已保存：{updated_skill['skill_name']}")
                st.rerun()

        if reset_skill_weights:
            default_skill = get_matching_skill_by_id(selected_skill_id)
            st.session_state.matching_skill_configs[selected_skill_id] = default_skill
            sync_matching_skill_to_profiles(default_skill)
            st.success(f"已恢复默认：{default_skill['skill_name']}")
            st.rerun()

        st.divider()

    if jd_workspace == "待确认草稿":
        if not st.session_state.jd_drafts:
            st.info("暂无待确认草稿。请先在“新建岗位”里生成 JD 草稿。")
        else:
            draft_id = st.selectbox("选择草稿", list(st.session_state.jd_drafts.keys()), key="draft_profile_selector")
            draft = st.session_state.jd_drafts[draft_id]
            draft_pkg = draft["package"]
            st.caption(f"Draft · Created at {draft.get('created_at', '')}")
            d1, d2 = st.columns([1.1, 0.9], gap="medium")
            with d1:
                st.text_area("对外 JD 草稿", value=draft_pkg.public_jd, height=300, key="draft_public_jd_preview")
            with d2:
                section_label("内部岗位画像草稿")
                st.json(draft_pkg.internal_profile)
                draft_skill = active_matching_skill_by_id(draft.get("matching_skill_id")) if draft.get("matching_skill_id") else active_matching_skill(
                    (draft.get("input_snapshot") or {}).get("job_family", "开发"),
                    (draft.get("input_snapshot") or {}).get("recruitment_type", "社招"),
                )
                section_label("绑定评分 Skill")
                st.markdown(f"**{draft_skill['skill_name']}**")
                st.caption(draft_skill["focus_summary"])
            if st.button("确认并创建岗位目录", type="primary", use_container_width=True, key="confirm_selected_draft_btn"):
                draft_skill = active_matching_skill_by_id(draft.get("matching_skill_id")) if draft.get("matching_skill_id") else active_matching_skill(
                    (draft.get("input_snapshot") or {}).get("job_family", "开发"),
                    (draft.get("input_snapshot") or {}).get("recruitment_type", "社招"),
                )
                st.session_state.confirmed_job_profiles[draft_id] = {
                    **draft,
                    "status": "confirmed",
                    "confirmed_at": datetime.now().isoformat(),
                    "version": "v1",
                    "matching_skill": draft_skill,
                    "matching_skill_id": draft_skill["skill_id"],
                }
                st.session_state.job_profiles[draft_id] = st.session_state.confirmed_job_profiles[draft_id]
                st.session_state.selected_confirmed_profile_id = draft_id
                del st.session_state.jd_drafts[draft_id]
                st.session_state.pending_jd_workspace = f"岗位：{draft_id}"
                _persist_job_profile_store()
                st.success(f"已确认岗位目录：{draft_id}")
                st.rerun()
            st.divider()

    if jd_workspace.startswith("岗位："):
        confirmed_id = jd_workspace.replace("岗位：", "", 1)
        confirmed = st.session_state.confirmed_job_profiles.get(confirmed_id)
        if confirmed:
            confirmed_pkg = confirmed["package"]
            st.caption(f"Confirmed · {confirmed.get('version', 'v1')} · Confirmed at {confirmed.get('confirmed_at', '')}")
            p1, p2 = st.columns([1.1, 0.9], gap="medium")
            with p1:
                st.text_area("对外 JD", value=confirmed_pkg.public_jd, height=300, key=f"confirmed_public_jd_preview_{confirmed_id}")
            with p2:
                section_label("内部岗位画像")
                st.json(confirmed_pkg.internal_profile)
                confirmed_skill = active_matching_skill_by_id(confirmed.get("matching_skill_id"))
                section_label("绑定评分 Skill")
                st.markdown(f"**{confirmed_skill['skill_name']}**")
                st.caption(confirmed_skill["focus_summary"])
                section_label("筛选策略")
                for item in confirmed_pkg.screening_strategy:
                    st.markdown(f"- {item}")
            st.divider()

    step_header("1","Generate Role JD Package")
    st.markdown("""
    <div style="background:#f8fbf8;border-left:3px solid #d5dfd7;padding:12px 14px;margin-bottom:14px">
      <div style="font-size:13px;color:#718078;line-height:1.6">
        Describe the role in one short paragraph. The system will infer structured fields,
        generate a candidate-facing JD, and prepare an internal job profile.
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("##### 基础信息")
    basic1, basic2, basic3 = st.columns(3, gap="medium")
    with basic1:
        gen_job_title = st.text_input("岗位名称", placeholder="后端研发工程师", key="gen_job_title")
        gen_job_level = st.selectbox(
            "岗位级别",
            ["", "校招", "初级", "中级", "高级", "专家", "管理岗"],
            key="gen_job_level",
        )
    with basic2:
        gen_department = st.text_input("所属业务部门", placeholder="支付业务部", key="gen_department")
        gen_job_family = st.selectbox(
            "岗位序列",
            ["开发"],
            key="gen_job_family",
            help="当前已支持开发序列的社招/校招评分 Skill。",
        )
    with basic3:
        gen_recruitment_type = st.selectbox(
            "招聘类型",
            ["", "社招", "校招", "实习", "外包", "转岗"],
            key="gen_recruitment_type",
        )
        gen_location = st.text_input("工作地点", placeholder="北京 / 上海 / 杭州 / 远程", key="gen_location")
        gen_hc_count = st.number_input("HC 数量", min_value=0, max_value=100, value=1, step=1, key="gen_hc_count")

    quick_request = st.text_area(
        "你想招什么人？",
        height=150,
        placeholder="例：主要做交易链路稳定性和高并发优化，希望有 Go/Java、Redis、MySQL、Kafka 经验，最好有支付或金融背景，沟通能力好，owner 意识强。优先研发院校 list 里的人。",
        key="quick_jd_request",
    )
    q1, q2 = st.columns([1, 1], gap="medium")
    with q1:
        quick_jd_style = st.selectbox("JD 风格", ["标准正式", "吸引候选人", "偏技术深度"], key="quick_jd_style")
    with q2:
        quick_screening_strictness = st.selectbox("筛选严格度", ["宽松", "标准", "严格"], index=1, key="quick_screening_strictness")

    qbtn1, qbtn2 = st.columns([1, 1], gap="medium")
    with qbtn1:
        infer_clicked = st.button("🔎 智能识别岗位信息", use_container_width=True, key="infer_jd_fields_btn")
    with qbtn2:
        infer_and_generate_clicked = st.button("✨ 智能识别并生成 JD", type="primary", use_container_width=True, key="infer_and_generate_jd_btn")

    if infer_clicked or infer_and_generate_clicked:
        if not has_required_api_key():
            st.error(f"{required_key_name()} is required — enter it in the sidebar.")
        elif not quick_request.strip():
            st.error("请先用一段话描述你想招什么人。")
        else:
            try:
                with st.spinner("正在识别岗位信息并补全结构化字段..."):
                    context_parts = []
                    if gen_job_title:
                        context_parts.append(f"岗位名称：{gen_job_title}")
                    if gen_department:
                        context_parts.append(f"所属业务部门：{gen_department}")
                    if gen_job_level:
                        context_parts.append(f"岗位级别：{gen_job_level}")
                    if gen_job_family:
                        context_parts.append(f"岗位序列：{gen_job_family}")
                    if gen_recruitment_type:
                        context_parts.append(f"招聘类型：{gen_recruitment_type}")
                    if gen_location:
                        context_parts.append(f"工作地点：{gen_location}")
                    if gen_hc_count:
                        context_parts.append(f"HC数量：{gen_hc_count}")
                    context_parts.append(f"岗位需求描述：{quick_request}")
                    inferred = infer_jd_fields(
                        hiring_request="\n".join(context_parts),
                        jd_style=quick_jd_style,
                        screening_strictness=quick_screening_strictness,
                    )
                field_key_map = {
                    "arrival_time": "gen_arrival_time",
                    "salary_range": "gen_salary_range",
                    "business_background": "gen_business_background",
                    "role_problem": "gen_role_problem",
                    "core_responsibilities": "gen_core_work",
                    "key_projects": "gen_key_projects",
                    "success_criteria": "gen_success_criteria",
                    "collaborators": "gen_collaborators",
                    "tech_stack": "gen_tech_stack",
                    "must_have_skills": "gen_must_have",
                    "nice_to_have_skills": "gen_nice_to_have",
                    "min_years": "gen_min_years",
                    "project_experience": "gen_project_exp",
                    "industry_experience": "gen_industry_exp",
                    "hr_soft_requirements": "gen_hr_needs",
                    "candidate_motivation": "gen_candidate_motivation",
                    "negative_signals": "gen_negative_signals",
                    "stability_requirement": "gen_stability_req",
                    "communication_requirement": "gen_communication_req",
                    "manual_offer_patterns": "gen_manual_offer_patterns",
                    "school_priority_rule": "gen_school_rule",
                }
                for src_key, widget_key in field_key_map.items():
                    value = inferred.get(src_key)
                    if widget_key and value not in (None, ""):
                        st.session_state[widget_key] = value
                st.session_state.inferred_jd_fields = inferred
                st.session_state.quick_generate_requested = bool(infer_and_generate_clicked)
                st.success("已识别岗位信息。你可以直接查看下方高级设置，也可以等待自动生成 JD。")
            except Exception as e:
                st.error(f"岗位信息识别失败: {e}")

    if st.session_state.inferred_jd_fields:
        inferred = st.session_state.inferred_jd_fields
        with st.expander("识别结果预览", expanded=True):
            preview_cols = st.columns(3, gap="medium")
            preview_cols[0].metric("岗位", inferred.get("job_title", "未识别"))
            preview_cols[1].metric("级别", inferred.get("job_level", "未识别"))
            preview_cols[2].metric("招聘类型", inferred.get("recruitment_type", "未识别"))
            st.markdown(f"**部门：** {inferred.get('department', '未识别')}")
            st.markdown(f"**业务方向：** {inferred.get('business_background', '')}")
            st.markdown(f"**核心任务：** {inferred.get('role_problem', '')}")
            st.markdown(f"**必备技能：** {inferred.get('must_have_skills', '')}")
            missing = inferred.get("missing_fields") or []
            if missing:
                st.caption("可选补充：" + "、".join(missing))

    with st.expander("高级设置：查看或微调识别出的岗位字段", expanded=False):
        st.caption("默认不用填写这里。系统会根据上面的一段话自动补全；需要更精细控制时再展开修改。")
        st.markdown("##### A. 更多基础信息")
        b1, b2 = st.columns(2, gap="medium")
        with b1:
            gen_arrival_time = st.selectbox(
                "到岗时间（推荐）",
                ["不限", "立即", "1个月内", "2个月内", "3个月内"],
                key="gen_arrival_time",
            )
        with b2:
            gen_salary_range = st.text_input("薪资范围（可选，内部使用）", placeholder="30k-45k * 15", key="gen_salary_range")

        st.markdown("##### B. 业务需求与工作职责")
        gen_business_background = st.text_area(
            "业务背景（必填）",
            height=90,
            placeholder="这个团队/业务线负责什么？当前处于什么阶段？",
            key="gen_business_background",
        )
        gen_role_problem = st.text_area(
            "岗位要解决的问题（必填）",
            height=90,
            placeholder="为什么现在要招这个岗位？需要解决什么业务痛点？",
            key="gen_role_problem",
        )
        gen_core_work = st.text_area(
            "核心工作内容（必填）",
            height=110,
            placeholder="建议 3-5 条。例：负责支付核心链路接口设计与开发；参与系统性能优化和稳定性治理...",
            key="gen_core_work",
        )
        w1, w2 = st.columns(2, gap="medium")
        with w1:
            gen_key_projects = st.text_area("未来 3-6 个月核心项目（推荐）", height=90, key="gen_key_projects")
        with w2:
            gen_success_criteria = st.text_area("成功标准（推荐）", height=90, key="gen_success_criteria")
        gen_collaborators = st.multiselect(
            "跨团队协作对象（可选）",
            ["产品", "测试", "算法", "风控", "运营", "数据团队", "设计", "销售", "客户成功"],
            key="gen_collaborators",
        )

        st.markdown("##### C. 硬技能与项目经验")
        h1, h2 = st.columns([1, 1], gap="medium")
        with h1:
            gen_tech_stack = st.text_area(
                "技术栈（必填）",
                height=90,
                placeholder="Go、Java、MySQL、Redis、Kafka、Kubernetes",
                key="gen_tech_stack",
            )
            gen_must_have = st.text_area(
                "必备技能（必填）",
                height=120,
                placeholder="- 熟悉后端服务开发\n- 熟悉数据库设计和性能优化\n- 理解高并发系统设计",
                key="gen_must_have",
            )
            gen_min_years = st.number_input("最低工作年限（推荐）", min_value=0, max_value=30, value=0, step=1, key="gen_min_years")
        with h2:
            gen_nice_to_have = st.text_area("加分技能（推荐）", height=120, key="gen_nice_to_have")
            gen_project_exp = st.text_area("必须有的项目经验（推荐）", height=90, key="gen_project_exp")
            gen_industry_exp = st.text_input("行业经验要求（可选）", placeholder="支付 / 电商 / 金融科技 / SaaS / 不限", key="gen_industry_exp")

        st.markdown("##### D. 软性要求与负向信号")
        s1, s2 = st.columns([1, 1], gap="medium")
        with s1:
            gen_hr_needs = st.text_area(
                "软性要求（推荐）",
                height=120,
                placeholder="- 沟通表达清晰\n- owner 意识强\n- 能主动同步风险",
                key="gen_hr_needs",
            )
            gen_candidate_motivation = st.text_area("候选人意愿要求（可选）", height=80, key="gen_candidate_motivation")
        with s2:
            gen_negative_signals = st.text_area(
                "不适合的人 / 负向信号（推荐）",
                height=120,
                placeholder="- 只想做单点开发，不愿意参与线上问题治理\n- 项目经验主要停留在 CRUD",
                key="gen_negative_signals",
            )
            gen_stability_req = st.selectbox("稳定性要求（可选）", ["不限", "低", "中", "高"], key="gen_stability_req")
            gen_communication_req = st.selectbox("沟通协作要求（可选）", ["不限", "低", "中", "高"], key="gen_communication_req")

        st.markdown("##### E. 外部资料包")
        d1, d2 = st.columns([1, 1], gap="medium")
        with d1:
            offer_file = st.file_uploader(
                "历史 offer 数据（推荐，CSV / Excel）",
                type=["csv", "xlsx", "xls"],
                key="offer_history_upload",
                help="Recommended columns: result, school, years, skills, project_keywords, interview_feedback, pass_reason, reject_reason.",
            )
            gen_manual_offer_patterns = st.text_area(
                "手动补充历史规律（可选）",
                height=90,
                placeholder="例：过去通过的人大多有支付系统经验，淘汰原因集中在项目深度不足。",
                key="gen_manual_offer_patterns",
            )
        with d2:
            school_file = st.file_uploader(
                "研发院校 list（推荐，CSV / Excel）",
                type=["csv", "xlsx", "xls"],
                key="school_list_upload",
                help="Recommended columns: school_name, alias, tier, category, notes.",
            )
            gen_school_rule = st.radio(
                "院校规则",
                ["仅作为加分项（推荐）", "强优先推荐", "作为硬性筛选条件"],
                index=0,
                key="gen_school_rule",
            )

        offer_records, offer_err = _read_uploaded_table(offer_file)
        school_records, school_err = _read_uploaded_table(school_file)
        if offer_file:
            st.info(f"Historical offer rows loaded: {len(offer_records)}" if not offer_err else offer_err)
        if school_file:
            st.info(f"School list rows loaded: {len(school_records)}" if not school_err else school_err)

    inferred_defaults = st.session_state.inferred_jd_fields or {}
    effective_job_title = gen_job_title or inferred_defaults.get("job_title", "")
    effective_job_level = gen_job_level or inferred_defaults.get("job_level", "")
    effective_job_family = gen_job_family or inferred_defaults.get("job_family", "开发")
    effective_recruitment_type = gen_recruitment_type or inferred_defaults.get("recruitment_type", "")
    effective_department = gen_department or inferred_defaults.get("department", "")
    effective_location = gen_location or inferred_defaults.get("location", "")
    effective_hc_count = gen_hc_count or inferred_defaults.get("hc_count", 1)

    required_missing = []
    for label, value in {
        "岗位名称": effective_job_title,
        "岗位级别": effective_job_level,
        "招聘类型": effective_recruitment_type,
        "岗位序列": effective_job_family,
        "所属部门": effective_department,
        "业务背景": gen_business_background,
        "岗位要解决的问题": gen_role_problem,
        "核心工作内容": gen_core_work,
        "技术栈": gen_tech_stack,
        "必备技能": gen_must_have,
    }.items():
        if not str(value).strip():
            required_missing.append(label)

    if required_missing:
        st.warning("生成 JD 前请补齐必填项：" + "、".join(required_missing))

    selected_matching_skill = active_matching_skill(effective_job_family, effective_recruitment_type)
    st.info(
        f"将绑定评分 Skill：{selected_matching_skill['skill_name']} · "
        f"{selected_matching_skill['focus_summary']}"
    )

    manual_generate_clicked = st.button(
        "✨ Generate JD package",
        type="primary",
        use_container_width=True,
        key="generate_jd_package_btn",
        disabled=bool(required_missing),
    )
    quick_generate_requested = bool(st.session_state.pop("quick_generate_requested", False))
    generate_jd_clicked = manual_generate_clicked or (quick_generate_requested and not required_missing)
    if quick_generate_requested and required_missing:
        st.error("智能识别后仍缺少必要信息，请展开高级设置补齐：" + "、".join(required_missing))

    if generate_jd_clicked:
        if not has_required_api_key():
            st.error(f"{required_key_name()} is required — enter it in the sidebar.")
        else:
            try:
                offer_summary = summarize_table_records(offer_records, "Historical offer data")
                school_summary = summarize_table_records(school_records, "R&D school priority list")
                with st.spinner("Generating JD package and internal screening profile..."):
                    st.session_state.generated_jd_package = generate_jd_package(
                        job_title=effective_job_title,
                        department=effective_department,
                        hr_soft_requirements=gen_hr_needs,
                        offer_data_summary=offer_summary,
                        school_list_summary=school_summary,
                        job_level=effective_job_level,
                        recruitment_type=effective_recruitment_type,
                        location=effective_location,
                        hc_count=str(effective_hc_count),
                        arrival_time=gen_arrival_time,
                        salary_range=gen_salary_range,
                        business_background=gen_business_background,
                        role_problem=gen_role_problem,
                        core_responsibilities=gen_core_work,
                        key_projects=gen_key_projects,
                        success_criteria=gen_success_criteria,
                        collaborators=", ".join(gen_collaborators),
                        tech_stack=gen_tech_stack,
                        must_have_skills=gen_must_have,
                        nice_to_have_skills=gen_nice_to_have,
                        min_years=str(gen_min_years) if gen_min_years else "",
                        project_experience=gen_project_exp,
                        industry_experience=gen_industry_exp,
                        candidate_motivation=gen_candidate_motivation,
                        negative_signals=gen_negative_signals,
                        stability_requirement=gen_stability_req,
                        communication_requirement=gen_communication_req,
                        manual_offer_patterns=gen_manual_offer_patterns,
                        school_priority_rule=gen_school_rule,
                    )
                st.success("JD package generated.")
            except Exception as e:
                st.error(f"JD generation failed: {e}")

    if st.session_state.generated_jd_package:
        pkg = st.session_state.generated_jd_package
        pkg_dict = pkg.model_dump() if hasattr(pkg, "model_dump") else pkg.dict()
        with st.expander("Generated JD package", expanded=True):
            result_public, result_profile, result_strategy, result_weights = st.tabs([
                "对外 JD",
                "内部岗位画像",
                "筛选策略",
                "评分权重",
            ])
            with result_public:
                st.text_area(
                    "Public JD",
                    value=pkg.public_jd,
                    height=320,
                    key="generated_public_jd_preview",
                )
            with result_profile:
                st.json(pkg.internal_profile)
            with result_strategy:
                section_label("Priority / caution / rejection rules")
                for item in pkg.screening_strategy:
                    st.markdown(f"- {item}")
                section_label("Interview focus")
                for item in pkg.interview_focus:
                    st.markdown(f"- {item}")
            with result_weights:
                section_label("Scoring weights")
                st.json(pkg.scoring_weights)

            action_col1, action_col2, action_col3 = st.columns(3, gap="medium")
            with action_col1:
                save_draft = st.button(
                    "保存为待确认草稿",
                    use_container_width=True,
                    key="save_generated_draft_btn",
                )
                if save_draft:
                    title = pkg.internal_profile.get("job_title") or effective_job_title or "Untitled role"
                    draft_id = f"{title} · {effective_department or '未命名部门'} · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    st.session_state.jd_drafts[draft_id] = {
                        "title": title,
                        "department": pkg.internal_profile.get("department") or effective_department,
                        "status": "draft",
                        "created_at": datetime.now().isoformat(),
                        "package": pkg,
                        "school_records": school_records,
                        "offer_records": offer_records,
                        "matching_skill": selected_matching_skill,
                        "matching_skill_id": selected_matching_skill["skill_id"],
                        "input_snapshot": {
                            "job_title": effective_job_title,
                            "job_level": effective_job_level,
                            "job_family": effective_job_family,
                            "recruitment_type": effective_recruitment_type,
                            "department": effective_department,
                            "location": effective_location,
                            "hc_count": effective_hc_count,
                            "arrival_time": gen_arrival_time,
                            "business_background": gen_business_background,
                            "role_problem": gen_role_problem,
                            "core_responsibilities": gen_core_work,
                            "tech_stack": gen_tech_stack,
                            "must_have_skills": gen_must_have,
                            "nice_to_have_skills": gen_nice_to_have,
                            "school_priority_rule": gen_school_rule,
                        },
                    }
                    _persist_job_profile_store()
                    st.success(f"已保存为待确认草稿：{draft_id}")
            with action_col2:
                confirm_profile = st.button(
                    "确认并创建岗位目录",
                    type="primary",
                    use_container_width=True,
                    key="confirm_generated_job_profile_btn",
                )
                if confirm_profile:
                    title = pkg.internal_profile.get("job_title") or effective_job_title or "Untitled role"
                    profile_id = f"{title} · {effective_department or '未命名部门'} · v1"
                    st.session_state.confirmed_job_profiles[profile_id] = {
                        "title": title,
                        "department": pkg.internal_profile.get("department") or effective_department,
                        "status": "confirmed",
                        "created_at": datetime.now().isoformat(),
                        "confirmed_at": datetime.now().isoformat(),
                        "version": "v1",
                        "package": pkg,
                        "school_records": school_records,
                        "offer_records": offer_records,
                        "matching_skill": selected_matching_skill,
                        "matching_skill_id": selected_matching_skill["skill_id"],
                        "input_snapshot": {
                            "job_title": effective_job_title,
                            "job_level": effective_job_level,
                            "job_family": effective_job_family,
                            "recruitment_type": effective_recruitment_type,
                            "department": effective_department,
                            "location": effective_location,
                            "hc_count": effective_hc_count,
                            "arrival_time": gen_arrival_time,
                            "business_background": gen_business_background,
                            "role_problem": gen_role_problem,
                            "core_responsibilities": gen_core_work,
                            "tech_stack": gen_tech_stack,
                            "must_have_skills": gen_must_have,
                            "nice_to_have_skills": gen_nice_to_have,
                            "school_priority_rule": gen_school_rule,
                        },
                    }
                    st.session_state.job_profiles[profile_id] = st.session_state.confirmed_job_profiles[profile_id]
                    st.session_state.selected_job_profile_id = profile_id
                    st.session_state.selected_confirmed_profile_id = profile_id
                    st.session_state.pending_jd_workspace = f"岗位：{profile_id}"
                    _persist_job_profile_store()
                    st.success(f"已确认并创建岗位目录：{profile_id}")
                    st.rerun()
            with action_col3:
                st.info("确认后的岗位才会进入简历筛选下拉框。")

            st.download_button(
                "↓ Download JD package JSON",
                data=json.dumps(pkg_dict, ensure_ascii=False, indent=2).encode("utf-8"),
                file_name=f"jd_package_{datetime.now().strftime('%Y%m%d_%H%M')}.json",
                mime="application/json",
                use_container_width=True,
            )

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: RESUME SCREENING
# ═══════════════════════════════════════════════════════════════════════════════
if active_page == "简历筛选":
    # Step 1: Select confirmed job JD
    step_header("1","选择岗位 JD")
    selected_screening_profile = None
    selected_screening_pkg = None
    selected_matching_skill = None
    jd_text = ""
    if st.session_state.confirmed_job_profiles:
        confirmed_ids = list(st.session_state.confirmed_job_profiles.keys())
        confirmed_default_idx = 0
        if st.session_state.selected_confirmed_profile_id in confirmed_ids:
            confirmed_default_idx = confirmed_ids.index(st.session_state.selected_confirmed_profile_id)
        screening_profile_id = st.selectbox(
            "使用已确认岗位档案",
            confirmed_ids,
            index=confirmed_default_idx,
            key="screening_confirmed_profile_selector",
        )
        screening_profile = st.session_state.confirmed_job_profiles[screening_profile_id]
        screening_pkg = screening_profile["package"]
        selected_screening_profile = screening_profile
        selected_screening_pkg = screening_pkg
        selected_matching_skill = active_matching_skill_by_id(screening_profile.get("matching_skill_id"))
        jd_text = screening_pkg.public_jd
        st.session_state.selected_confirmed_profile_id = screening_profile_id
        s0c1, s0c2 = st.columns([1, 1], gap="medium")
        with s0c1:
            st.caption(
                f"Confirmed · {screening_profile.get('version', 'v1')} · "
                f"{screening_profile.get('department', '')}"
            )
            st.info(f"当前评分 Skill：{selected_matching_skill['skill_name']} · {selected_matching_skill['focus_summary']}")
            st.text_area(
                "岗位 JD",
                value=screening_pkg.public_jd,
                height=220,
                disabled=True,
                key=f"screening_selected_jd_{screening_profile_id}",
            )
        with s0c2:
            with st.expander("查看岗位画像"):
                st.json(screening_pkg.internal_profile)
                section_label("评分 Skill")
                st.json({
                    "skill_id": selected_matching_skill["skill_id"],
                    "skill_name": selected_matching_skill["skill_name"],
                    "dimension_weights": selected_matching_skill["dimension_weights"],
                    "positive_signals": selected_matching_skill["positive_signals"],
                    "negative_signals": selected_matching_skill["negative_signals"],
                })
                section_label("筛选策略")
                for item in screening_pkg.screening_strategy:
                    st.markdown(f"- {item}")
    else:
        st.info("暂无已确认岗位档案。请先在 JD生成 功能里生成草稿，并点击确认创建岗位目录。")

    # Step 2: Upload candidate resumes
    step_header("2","上传人选简历")
    st.markdown('<div style="font-size:13px;font-weight:500;color:#1c2a22;margin-bottom:10px">Candidate resumes</div>', unsafe_allow_html=True)
    candidate_files = st.file_uploader(
        "",
        accept_multiple_files=True,
        key="candidate_files",
        label_visibility="collapsed",
        help="上传人选简历。当前可解析：PDF、DOCX/DOC、TXT、Markdown、CSV、JSON。",
    )
    total = len(candidate_files)
    if total:
        st.info(f"✓ {total} candidate file(s) queued and ready")

    # Step 3: Run matching
    step_header("3","开始匹配")
    st.markdown("""
    <div style="background:#ffffff;border:1px solid #e4ebe5;border-radius:12px;padding:16px;margin-bottom:8px">
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px">
        <div style="background:#f5f8f4;border-radius:8px;padding:10px;border:1px solid #e4ebe5">
          <div style="font-size:10px;color:#98a49d;margin-bottom:2px;font-family:JetBrains Mono,monospace">LLM</div>
          <div style="font-size:13px;font-weight:500;color:#1c2a22">""" + provider_label() + """</div>
        </div>
        <div style="background:#f5f8f4;border-radius:8px;padding:10px;border:1px solid #e4ebe5">
          <div style="font-size:10px;color:#98a49d;margin-bottom:2px;font-family:JetBrains Mono,monospace">Embeddings</div>
          <div style="font-size:13px;font-weight:500;color:#1c2a22">MiniLM-L6-v2</div>
        </div>
        <div style="background:#f5f8f4;border-radius:8px;padding:10px;border:1px solid #e4ebe5">
          <div style="font-size:10px;color:#98a49d;margin-bottom:2px;font-family:JetBrains Mono,monospace">Validation</div>
          <div style="font-size:13px;font-weight:500;color:#1c2a22">Pydantic v2</div>
        </div>
      </div>
    """, unsafe_allow_html=True)

    save_to_pool = st.checkbox(
        "Add successful candidates to Talent Pool",
        value=True,
        help="Automatically ingest evaluated candidates into the Resume Open Source library",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    run_clicked = st.button("▶  开始人岗匹配", type="primary",
                             use_container_width=True, key="run_btn",
                             disabled=not bool(jd_text.strip()))

    if run_clicked:
        if not has_required_api_key():
            st.error(f"{required_key_name()} is required — enter it in the sidebar."); st.stop()
        if not jd_text.strip():
            st.error("请先选择一个已确认岗位 JD。"); st.stop()

        all_profiles = []
        for f in candidate_files:
            try:
                content = f.getvalue()
                if Path(f.name).suffix.lower() == ".json":
                    data = json.loads(content.decode("utf-8"))
                    txt = extract_text_from_json(data)
                    if txt:
                        all_profiles.append((f.name, txt))
                else:
                    all_profiles.append((f.name, content))
            except Exception as e:
                st.warning(f"Candidate file error: {f.name} — {e}")
        if not all_profiles:
            st.error("请至少上传一份候选人简历。")
            st.stop()

        prog   = st.progress(0, text="Starting pipeline...")
        status = st.empty()
        errors = []

        status.info("Parsing selected job JD...")
        try:
            parsed_jd = parse_jd(jd_text)
            st.session_state.parsed_jd = parsed_jd
            status.success(f"Job JD parsed — {parsed_jd.job_title} · {parsed_jd.seniority_level}")
            prog.progress(10); time.sleep(0.2)
        except Exception as e:
            st.error(f"JD parsing failed: {e}"); st.stop()

        candidates = []
        n = len(all_profiles)
        for i,(fname,content) in enumerate(all_profiles):
            status.info(f"Parsing profile {i+1} of {n} — {fname}")
            try:
                raw = content if isinstance(content,str) else extract_text_from_file(content,fname)
                if not raw.strip(): errors.append(f"Empty: {fname}"); continue
                candidates.append(parse_profile(raw, source_file=fname))
                prog.progress(10+int(40*(i+1)/n))
            except Exception as e:
                errors.append(f"Parse error — {fname}: {e}")

        if errors:
            with st.expander("查看解析问题", expanded=not candidates):
                for err in errors:
                    st.warning(err)
        if not candidates:
            st.error("无法解析任何候选人简历。请检查文件是否为可复制文本 PDF、DOCX、TXT、Markdown、CSV 或 JSON；扫描版 PDF 需要先 OCR。")
            st.stop()

        results = []
        for i,profile in enumerate(candidates):
            status.info(f"Scoring {i+1} of {len(candidates)} — {profile.candidate_name}")
            try:
                scores = score_candidate(parsed_jd, profile, selected_matching_skill)
                results.append(CandidateResult(profile=profile, scores=scores))
                prog.progress(50+int(40*(i+1)/len(candidates)))
            except Exception as e:
                errors.append(f"Scoring error — {profile.candidate_name}: {e}")

        if not results: st.error("Scoring failed for all candidates."); st.stop()

        ranked = rank_candidates(results)
        st.session_state.ranked       = ranked
        st.session_state.run_complete = True
        st.session_state.last_screening_profile_id = screening_profile_id if selected_screening_profile else ""
        st.session_state.last_screening_department = selected_screening_profile.get("department", "") if selected_screening_profile else ""
        st.session_state.interview_cache = {}
        prog.progress(95)

        if save_to_pool:
            saved, msgs = ingest_candidates(ranked, parsed_jd, only_recommended=True)
            if saved:
                status.success(f"✓ Evaluated {len(ranked)} candidates · {saved} added to Talent Pool")
            else:
                status.success(f"✓ Evaluated {len(ranked)} candidates")
        else:
            status.success(f"✓ Complete — {len(ranked)} candidates matched and ranked")

        prog.progress(100)
        if errors:
            with st.expander(f"{len(errors)} warning(s)"):
                for e in errors: st.warning(e)

    # Step 4: Results
    if st.session_state.run_complete and st.session_state.ranked:
        ranked = st.session_state.ranked
        jd     = st.session_state.parsed_jd

        step_header("4","人岗匹配结果")
        pending_screening_success = st.session_state.pop("pending_screening_success", "")
        if pending_screening_success:
            st.success(pending_screening_success)

        rec = {}
        for c in ranked:
            r = c.hire_recommendation.value
            rec[r] = rec.get(r,0)+1

        m = st.columns(5)
        m[0].metric("Total",       len(ranked))
        m[1].metric("Strong hire", rec.get("Strong Hire",0))
        m[2].metric("Hire",        rec.get("Hire",0))
        m[3].metric("Maybe",       rec.get("Maybe",0))
        m[4].metric("No hire",     rec.get("No Hire",0))

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        section_label("Candidate comparison — radar chart")
        st.caption("Select two or more candidates to compare across all five scoring dimensions.")
        names = [f"#{c.rank} {c.profile.candidate_name}" for c in ranked]
        sel   = st.multiselect("", names, default=names[:min(3,len(names))],
                                key="radar", label_visibility="collapsed")
        if len(sel) >= 2:
            COLORS = ["#36c873","#4f8ff7","#8b5cf6","#d4a72c","#69d59a","#78a8f8"]
            fig = go.Figure()
            for i,c in enumerate([x for x in ranked if f"#{x.rank} {x.profile.candidate_name}" in sel]):
                vals = [getattr(c.scores, dim_key).score for dim_key in DIMENSION_LABELS]
                fig.add_trace(go.Scatterpolar(
                    r=vals+[vals[0]], theta=DIM_SHORT+[DIM_SHORT[0]],
                    fill="toself",
                    name=f"#{c.rank} {c.profile.candidate_name} ({c.weighted_total:.1f}/10)",
                    line_color=COLORS[i%len(COLORS)], opacity=0.75, line=dict(width=2)
                ))
            fig.update_layout(
                polar=dict(
                    bgcolor="#ffffff",
                    radialaxis=dict(visible=True, range=[0,10],
                        tickfont=dict(size=9,color="#98a49d",family="Inter"),
                        gridcolor="#edf2ee", linecolor="#d5dfd7"),
                    angularaxis=dict(gridcolor="#edf2ee", linecolor="#d5dfd7",
                        tickfont=dict(size=11,color="#718078",family="Inter"))
                ),
                paper_bgcolor="#ffffff", plot_bgcolor="#ffffff",
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.25,
                    font=dict(size=11,color="#718078",family="Inter"),
                    bgcolor="#ffffff", bordercolor="#e4ebe5", borderwidth=1),
                height=400, margin=dict(t=20,b=90,l=40,r=40)
            )
            st.plotly_chart(fig, use_container_width=True)
        elif len(sel)==1:
            st.info("Select at least two candidates to compare.")

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        section_label(f"Ranked person-job match — {jd.job_title}")

        for candidate in ranked:
            rec_val = candidate.hire_recommendation.value
            bc      = BADGE_COLOR.get(rec_val,"gray")
            gap     = get_skills_gap(jd, candidate.profile)
            sc      = candidate.weighted_total

            with st.expander(
                f"#{candidate.rank}  {candidate.profile.candidate_name}  ·  {sc:.1f}/10  ·  {rec_val}",
                expanded=(candidate.rank<=2)
            ):
                left, right = st.columns([3,1], gap="large")

                with left:
                    tags = badge_html(rec_val,bc)
                    tags += badge_html(f"{candidate.profile.total_experience_years} yrs exp","gray")
                    tags += badge_html(f"{len(candidate.profile.skills)} skills","gray")
                    tags += badge_html(candidate.scores.matching_skill_name,"blue")
                    st.markdown(f'<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px">{tags}</div>', unsafe_allow_html=True)

                    section_label("Skills gap analysis")
                    display_gaps = candidate.scores.gaps or gap
                    if display_gaps:
                        pills = "".join([f'<span style="display:inline-block;background:rgba(218,54,51,0.1);color:#f85149;border:1px solid rgba(218,54,51,0.3);border-radius:20px;padding:2px 8px;font-size:11px;margin:2px">✕ {s}</span>' for s in display_gaps[:10]])
                        st.markdown(pills, unsafe_allow_html=True)
                    else:
                        st.markdown('<span style="display:inline-block;background:rgba(35,134,54,0.1);color:#30b86a;border:1px solid rgba(35,134,54,0.3);border-radius:20px;padding:2px 10px;font-size:11px">✓ All required skills present</span>', unsafe_allow_html=True)

                    if candidate.scores.hard_checks:
                        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                        section_label("Hard checks")
                        for item in candidate.scores.hard_checks[:6]:
                            st.markdown(f"- {item}")

                    if candidate.scores.matched_evidence:
                        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                        section_label("Matched evidence")
                        for item in candidate.scores.matched_evidence[:6]:
                            st.markdown(f"- {item}")

                    if candidate.scores.risks:
                        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                        section_label("Risk signals")
                        for item in candidate.scores.risks[:5]:
                            st.markdown(f"- {item}")

                    if candidate.scores.suggested_action:
                        st.markdown(
                            f'<div style="margin-top:12px;padding:8px 12px;background:rgba(79,156,249,0.1);'
                            f'border:1px solid rgba(79,156,249,0.3);border-radius:8px;font-size:12px;color:#4f8ff7">'
                            f"Suggested action: {candidate.scores.suggested_action}</div>",
                            unsafe_allow_html=True,
                        )

                    if candidate.scores.algorithm_signals:
                        with st.expander("查看本地匹配算法信号"):
                            st.json(candidate.scores.algorithm_signals)

                    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                    section_label("Scoring rubric")
                    rows_html = '<div style="border-top:1px solid #e4ebe5">'
                    for dim_key,(dim_label,_) in DIMENSION_LABELS.items():
                        dim = getattr(candidate.scores, dim_key)
                        weight_value = float(candidate.scores.dimension_weights.get(dim_key, 0))
                        weight = f"{int(round(weight_value * 100))}%"
                        rows_html += dim_row_html(dim_label, weight, dim.score, dim.justification)
                    rows_html += '</div>'
                    st.markdown(rows_html, unsafe_allow_html=True)

                    if candidate.override_applied:
                        st.markdown(f'<div style="margin-top:10px;padding:8px 12px;background:rgba(163,113,247,0.1);border:1px solid rgba(163,113,247,0.3);border-radius:8px;font-size:12px;color:#8b5cf6">Override: {candidate.override_reason}</div>', unsafe_allow_html=True)

                    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
                    section_label("Tailored interview questions")
                    ck = f"iq_{candidate.profile.candidate_name}"
                    if ck in st.session_state.interview_cache:
                        iq = st.session_state.interview_cache[ck]
                        iq_html = ""
                        for i,q in enumerate(iq.get("technical_questions",[]),1):
                            iq_html += iq_block_html(f"Technical question {i}", q,"#4f8ff7","#4f8ff7")
                        for i,q in enumerate(iq.get("gap_questions",[]),1):
                            iq_html += iq_block_html(f"Gap probe {i}", q,"#36c873","#36c873")
                        cq = iq.get("culture_question","")
                        if cq: iq_html += iq_block_html("Behavioural question", cq,"#30b86a","#30b86a")
                        st.markdown(iq_html, unsafe_allow_html=True)
                    else:
                        if st.button("Generate interview questions",
                                      key=f"iq_{candidate.rank}", use_container_width=True):
                            with st.spinner("Generating tailored questions..."):
                                try:
                                    iq = generate_interview_questions(jd, candidate.profile, candidate.scores)
                                    st.session_state.interview_cache[ck] = iq
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Could not generate: {e}")

                with right:
                    sc_col = score_color(candidate.weighted_total)
                    st.markdown(f"""
                    <div style="background:#f5f8f4;border:1px solid #e4ebe5;border-radius:12px;
                                padding:16px;text-align:center;margin-bottom:12px">
                      <div style="font-size:2.4rem;font-weight:600;color:{sc_col};line-height:1">
                        {candidate.weighted_total:.1f}
                      </div>
                      <div style="font-size:11px;color:#98a49d;margin-top:4px;
                                   font-family:JetBrains Mono,monospace">out of 10.0</div>
                      <div style="margin-top:10px">{badge_html(rec_val,bc)}</div>
                    </div>""", unsafe_allow_html=True)

                    decision_key = _screening_decision_key(candidate, st.session_state.last_screening_profile_id)
                    current_decision = st.session_state.screening_decisions.get(decision_key, {})
                    section_label("HR 人才梯队")
                    st.caption("点击后直接进入待反馈阶段，不需要在这里填写原因。")
                    if current_decision:
                        decision_color = "green" if current_decision.get("decision") == "推荐" else "red" if current_decision.get("decision") == "不推荐" else "amber"
                        st.markdown(
                            f'<div style="margin-bottom:10px">{badge_html(current_decision.get("decision", "待定"), decision_color)} '
                            f'{badge_html(current_decision.get("talent_tier", ""), "gray")}</div>',
                            unsafe_allow_html=True,
                        )
                    d1, d2, d3 = st.columns(3)
                    with d1:
                        if st.button("推荐", type="primary", use_container_width=True, key=f"screening_recommend_{candidate.rank}"):
                            _record_screening_tier(candidate, jd, "推荐", "第一梯队")
                            st.rerun()
                    with d2:
                        if st.button("待定", use_container_width=True, key=f"screening_pending_{candidate.rank}"):
                            _record_screening_tier(candidate, jd, "待定", "第二梯队")
                            st.rerun()
                    with d3:
                        if st.button("不推荐", use_container_width=True, key=f"screening_reject_{candidate.rank}"):
                            _record_screening_tier(candidate, jd, "不推荐", "第三梯队")
                            st.rerun()

                    st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                    section_label("HR override")
                    odim = st.selectbox("", list(DIMENSION_LABELS.keys()),
                        format_func=lambda k: DIMENSION_LABELS[k][0],
                        key=f"odim_{candidate.rank}", label_visibility="collapsed")
                    oscore = st.slider("", 0.0, 10.0,
                        getattr(candidate.scores, odim).score,
                        step=0.5, key=f"oscore_{candidate.rank}",
                        label_visibility="collapsed")
                    oreason = st.text_input("", key=f"oreason_{candidate.rank}",
                        placeholder="Reason for override...",
                        label_visibility="collapsed")
                    if st.button("Apply override", key=f"obtn_{candidate.rank}",
                                  use_container_width=True):
                        if not oreason.strip(): st.error("Reason required.")
                        else:
                            apply_override(candidate, odim, oscore, oreason)
                            st.session_state.ranked = rank_candidates(ranked)
                            st.success("Override applied.")
                            st.rerun()

        # Step 5: Export + Talent Pool save
        step_header("5","Export & Save")
        ts   = datetime.now().strftime("%Y%m%d_%H%M")
        slug = jd.job_title.replace(" ","_")
        c1,c2,c3,c4 = st.columns(4, gap="medium")

        with c1:
            section_label("HTML report")
            st.caption("Self-contained · opens in any browser")
            if st.button("Generate HTML", use_container_width=True, key="gen_html"):
                with tempfile.NamedTemporaryFile(suffix=".html",delete=False) as tmp:
                    generate_html_report(ranked,jd,tmp.name)
                    data = Path(tmp.name).read_bytes()
                st.download_button("↓ Download HTML", data=data,
                    file_name=f"talentos_{slug}_{ts}.html",
                    mime="text/html", use_container_width=True)

        with c2:
            section_label("JSON export")
            st.caption("Structured data · ATS-ready")
            if st.button("Generate JSON", use_container_width=True, key="gen_json"):
                with tempfile.NamedTemporaryFile(suffix=".json",delete=False,mode="w") as tmp:
                    generate_json_export(ranked,jd,tmp.name)
                    data = Path(tmp.name).read_bytes()
                st.download_button("↓ Download JSON", data=data,
                    file_name=f"talentos_{slug}_{ts}.json",
                    mime="application/json", use_container_width=True)

        with c3:
            section_label("CSV spreadsheet")
            st.caption("Excel-compatible · all scores")
            if st.button("Generate CSV", use_container_width=True, key="gen_csv"):
	                rows = []
	                for c in ranked:
	                    decision = st.session_state.screening_decisions.get(
	                        _screening_decision_key(c, st.session_state.last_screening_profile_id),
	                        {},
	                    )
	                    rows.append({
	                        "Rank": c.rank,
	                        "Name": c.profile.candidate_name,
	                        "Source": c.profile.source_file,
	                        "Experience (yrs)": c.profile.total_experience_years,
	                        "Skills listed": len(c.profile.skills),
	                        "Weighted total": round(c.weighted_total, 2),
	                        "AI recommendation": c.hire_recommendation.value,
	                        "HR screening decision": decision.get("decision", ""),
	                        "Talent tier": decision.get("talent_tier", ""),
	                        "Matching skill": c.scores.matching_skill_name,
	                        "Hard skills": c.scores.hard_skills_match.score,
	                        "Business/projects": c.scores.business_project_match.score,
	                        "Seniority/level": c.scores.seniority_level_match.score,
	                        "Education/school": c.scores.education_school_match.score,
	                        "Soft requirements": c.scores.soft_requirements_match.score,
	                        "Low-risk signal": c.scores.risk_signal_control.score,
	                        "Hard checks": " | ".join(c.scores.hard_checks),
	                        "Matched evidence": " | ".join(c.scores.matched_evidence),
	                        "Gaps": " | ".join(c.scores.gaps or get_skills_gap(jd, c.profile)),
	                        "Risks": " | ".join(c.scores.risks),
	                        "Suggested action": c.scores.suggested_action,
	                        "Required skill coverage": c.scores.algorithm_signals.get("required_skill_coverage", ""),
	                        "Preferred skill coverage": c.scores.algorithm_signals.get("preferred_skill_coverage", ""),
	                        "Baseline total": c.scores.algorithm_signals.get("baseline_weighted_total", ""),
	                        "Override note": c.override_reason or "",
	                    })
	                csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
	                st.download_button(
	                    "↓ Download CSV",
	                    data=csv,
	                    file_name=f"talentos_{slug}_{ts}.csv",
	                    mime="text/csv",
	                    use_container_width=True,
	                )

        with c4:
            section_label("Add to Talent Pool")
            st.caption("Save for future open-source search")
            if st.button("➕ Ingest all recommended", use_container_width=True, key="ingest_btn"):
                saved, msgs = ingest_candidates(ranked, jd, only_recommended=True)
                for m in msgs[:5]: st.success(m)
                if len(msgs) > 5: st.info(f"... and {len(msgs)-5} more")
                if saved:
                    st.success(f"🎉 {saved} candidates added to Talent Pool module")

    step_header("6","待反馈候选人")
    st.caption("所有已分梯队的人才都会进入这里。请补充后续是否通过面试、未通过面试或未通过业务筛选，并填写原因。")
    followup_stats = candidate_followup_stats()
    f_m1, f_m2, f_m3 = st.columns(3)
    f_m1.metric("待反馈", followup_stats.get("待反馈", 0))
    f_m2.metric("已反馈", followup_stats.get("已反馈", 0))
    f_m3.metric("全部追踪", followup_stats.get("total", 0))

    pending_followup_filter = st.session_state.pop("pending_followup_status_filter", None)
    if pending_followup_filter in {"待反馈", "已反馈", "全部"}:
        st.session_state["followup_status_filter"] = pending_followup_filter
    pending_followup_success = st.session_state.pop("pending_followup_success", "")
    if pending_followup_success:
        st.success(pending_followup_success)

    followup_filter = st.radio(
        "反馈状态",
        ["待反馈", "已反馈", "全部"],
        horizontal=True,
        key="followup_status_filter",
    )
    status_filter = None if followup_filter == "全部" else followup_filter
    followups = list_candidate_followups(status=status_filter, limit=200)

    if not followups:
        st.info("暂无候选人反馈记录。请先在匹配结果里点击“推荐 / 待定 / 不推荐”完成梯队判断。")
    else:
        followup_options = {
            f"#{item['id']} · {item['candidate_name']} · {item['job_title']} · {item['current_status']}": item
            for item in followups
        }
        selected_followup_label = st.selectbox(
            "选择候选人填写/查看反馈",
            list(followup_options.keys()),
            key="selected_followup_record",
        )
        selected_followup = followup_options[selected_followup_label]

        info_col, form_col = st.columns([1, 1.4], gap="large")
        with info_col:
            st.markdown("##### 初筛记录")
            st.json({
                "candidate": selected_followup["candidate_name"],
                "job_profile_id": selected_followup["job_profile_id"],
                "job_title": selected_followup["job_title"],
                "department": selected_followup["department"],
                "matching_skill": selected_followup["matching_skill_name"],
                "initial_score": selected_followup["initial_score"],
                "ai_recommendation": selected_followup["initial_recommendation"],
                "hr_screening_decision": selected_followup.get("hr_screening_decision", ""),
                "talent_tier": selected_followup.get("talent_tier", ""),
                "current_status": selected_followup["current_status"],
            })
            with st.expander("查看初筛证据快照"):
                st.json(selected_followup.get("score_snapshot", {}))

        with form_col:
            st.markdown("##### 填写后续反馈")
            with st.form(f"followup_form_{selected_followup['id']}"):
                outcome_options = ["请选择后续结果", "通过面试", "未通过面试", "未通过业务筛选"]
                current_outcome = selected_followup.get("final_result") or "请选择后续结果"
                if current_outcome not in outcome_options:
                    current_outcome = "请选择后续结果"
                followup_outcome = st.selectbox(
                    "后续结果",
                    outcome_options,
                    index=outcome_options.index(current_outcome),
                )
                feedback_reason = st.text_area(
                    "反馈原因 / 说明",
                    value=selected_followup.get("hr_note") or selected_followup.get("fail_reason") or "",
                    height=110,
                    placeholder="例如：业务认可项目经历并通过面试；技术深度不足未通过面试；业务认为项目方向不匹配。",
                )
                submitted = st.form_submit_button("保存反馈", type="primary", use_container_width=True)

            if submitted:
                if followup_outcome == "请选择后续结果":
                    st.error("请选择后续结果。")
                elif not feedback_reason.strip():
                    st.error("请填写对应的反馈原因或说明。")
                else:
                    outcome_map = {
                        "通过面试": ("通过", "面试通过", ""),
                        "未通过面试": ("通过", "面试未通过", feedback_reason.strip()),
                        "未通过业务筛选": ("不通过", "未面试", feedback_reason.strip()),
                    }
                    business_result, interview_stage, fail_reason = outcome_map[followup_outcome]
                    update_candidate_followup(
                        selected_followup["id"],
                        business_review_result=business_result,
                        interview_stage=interview_stage,
                        final_result=followup_outcome,
                        fail_reason=fail_reason,
                        hr_note=feedback_reason.strip(),
                        current_status="已反馈",
                    )
                    st.session_state.pending_followup_status_filter = "已反馈"
                    st.session_state.pending_followup_success = "反馈已保存。后续会基于这些样本生成 Skill 优化建议。"
                    st.rerun()

# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2: TALENT POOL (RESUME OPEN SOURCE)
# ═══════════════════════════════════════════════════════════════════════════════
if active_page == "人才开源":
    source_stats = sourcing_stats()
    ts = talent_stats()

    k1,k2,k3 = st.columns(3)
    k1.markdown(_kpi("寻访任务", source_stats["tasks"], "已创建任务", "#36c873"), unsafe_allow_html=True)
    k2.markdown(_kpi("候选线索", source_stats["candidates"], f"{source_stats['pending']} 条待确认", "#4f8ff7"), unsafe_allow_html=True)
    k3.markdown(_kpi("已确认入库", source_stats["in_pool"], "由 HR 确认", "#30b86a"), unsafe_allow_html=True)
    k4,k5,k6 = st.columns(3)
    k4.markdown(_kpi("人才总量", ts["total"], f"{ts['active']} 名活跃人才", "#8b5cf6"), unsafe_allow_html=True)
    dom_name, dom_count = list(ts["by_domain"].items())[0] if ts["by_domain"] else ("–", 0)
    k5.markdown(_kpi("主要方向", dom_name[:18], f"{dom_count} 份档案", "#d4a72c"), unsafe_allow_html=True)
    k6.markdown(_kpi("平均经验", f"{ts['avg_experience_years']} 年", "人才库均值", "#30b86a"), unsafe_allow_html=True)

    all_sourcing_tasks = list_sourcing_tasks(limit=100)
    with st.expander("任务与数据源总览", expanded=bool(all_sourcing_tasks)):
        st.markdown(_sourcing_source_readiness_cards(), unsafe_allow_html=True)
        if all_sourcing_tasks:
            st.dataframe(
                pd.DataFrame(_sourcing_task_progress_rows(all_sourcing_tasks)),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.markdown(
                """
                <div class="sourcing-dashboard-note">
                  当前没有寻访任务。先创建寻访画像并确认策略，再进入候选线索核验。
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()

    if "sourcing_sub_view" not in st.session_state:
        st.session_state["sourcing_sub_view"] = "1. 开源寻访画像"
    sourcing_sub_view = st.segmented_control(
        "人才开源子功能",
        ["1. 开源寻访画像", "2. 候选线索核验", "3. 开源人才库沉淀"],
        key="sourcing_sub_view",
        label_visibility="collapsed",
    )
    sourcing_sub_view = sourcing_sub_view or "1. 开源寻访画像"

    if sourcing_sub_view == "1. 开源寻访画像":
        with st.container(border=True):
            st.markdown("""
            <div class="sourcing-card-title"><span class="sourcing-card-icon">1</span>创建寻访画像</div>
            <div class="sourcing-card-sub">选择岗位来源并补充业务画像，系统会自动保存草稿。</div>
            """, unsafe_allow_html=True)
            section_label("Create sourcing task")
            profile_options = ["不关联岗位"] + list(st.session_state.confirmed_job_profiles.keys())
            _init_sourcing_form_draft(profile_options)
            creation_mode = st.radio(
                "创建方式",
                ["手动输入", "从已有岗位 JD 创建"],
                horizontal=True,
                key="src_creation_mode",
                on_change=_save_sourcing_form_draft,
            )
            if creation_mode == "从已有岗位 JD 创建":
                confirmed_profile_ids = list(st.session_state.confirmed_job_profiles.keys())
                if not confirmed_profile_ids:
                    st.warning("暂无已确认岗位 JD，请先在 JD 生成模块确认岗位。")
                else:
                    source_profile_id = st.selectbox(
                        "选择已有岗位 JD",
                        confirmed_profile_ids,
                        key="src_source_job_profile",
                        on_change=_save_sourcing_form_draft,
                    )
                    if st.button("载入岗位 JD", use_container_width=True, key="load_sourcing_job_profile"):
                        _load_sourcing_fields_from_job_profile(source_profile_id)
                        st.session_state.pending_sourcing_form_success = f"已载入岗位 JD：{source_profile_id}"
                        st.rerun()
            pending_form_success = st.session_state.pop("pending_sourcing_form_success", "")
            if pending_form_success:
                st.success(pending_form_success)
            st.caption("字段会自动保存为本地草稿，刷新页面后会恢复；生成策略后也不会清空。")
            task_name = st.text_input(
                "寻访任务名称",
                placeholder="例如：大模型 Agent 算法专家寻访",
                key="src_task_name",
                on_change=_save_sourcing_form_draft,
            )
            c1, c2 = st.columns(2)
            with c1:
                talent_direction = st.selectbox(
                    "人才方向",
                    ["大模型", "推荐算法", "搜索算法", "广告算法", "CV", "NLP", "多模态", "数据科学", "其他"],
                    key="src_direction",
                    on_change=_save_sourcing_form_draft,
                )
            with c2:
                target_level = st.selectbox(
                    "目标级别",
                    ["资深工程师", "专家", "技术负责人", "科研型人才", "潜力人才"],
                    key="src_level",
                    on_change=_save_sourcing_form_draft,
                )
            business_scene = st.text_input(
                "业务场景",
                placeholder="例如：AI Agent、RAG、广告排序、内容推荐",
                key="src_scene",
                on_change=_save_sourcing_form_draft,
            )
            focus_signals = st.multiselect(
                "重点信号",
                ["顶会论文", "开源项目", "大厂经历", "技术博客", "专利", "公开演讲", "团队管理经验", "工程落地经验"],
                key="src_signals",
                on_change=_save_sourcing_form_draft,
            )
            exclusion_rules = st.text_input(
                "排除条件",
                placeholder="例如：纯学术暂不考虑、不考虑海外、无工业经验暂不考虑",
                key="src_exclusions",
                on_change=_save_sourcing_form_draft,
            )
            location_preference = st.text_input(
                "地域偏好",
                placeholder="例如：北京、上海、深圳、杭州、国内优先",
                key="src_location",
                on_change=_save_sourcing_form_draft,
            )
            linked_job_profile_id = st.selectbox(
                "关联岗位 JD",
                profile_options,
                key="src_linked_profile",
                on_change=_save_sourcing_form_draft,
            )
            description = st.text_area(
                "补充描述（选填）",
                placeholder="选填。可以用自然语言补充你想找什么样的人，例如：我想找做过大模型 Agent 落地的人，最好有工程经验和论文背景。",
                height=140,
                key="src_description",
                on_change=_save_sourcing_form_draft,
            )
            submitted = st.button("生成寻访策略", type="primary", use_container_width=True)

            if submitted:
                _save_sourcing_form_draft()
                task_name_value = (st.session_state.get("src_task_name") or task_name or "").strip()
                business_scene_value = (st.session_state.get("src_scene") or business_scene or "").strip()
                description_value = (st.session_state.get("src_description") or description or "").strip()
                exclusion_rules_value = (st.session_state.get("src_exclusions") or exclusion_rules or "").strip()
                location_preference_value = (st.session_state.get("src_location") or location_preference or "").strip()

                if not task_name_value:
                    task_name_value = f"{talent_direction}·{target_level}人才寻访"
                if not business_scene_value:
                    business_scene_value = f"{talent_direction}方向{target_level}寻访"
                if not description_value:
                    signal_text = "、".join(focus_signals) if focus_signals else "公开成果"
                    description_value = (
                        f"寻找{talent_direction}方向的{target_level}，"
                        f"业务场景为{business_scene_value}，重点关注{signal_text}。"
                    )
                task_payload = {
                    "task_name": task_name_value,
                    "talent_direction": talent_direction,
                    "target_level": target_level,
                    "business_scene": business_scene_value,
                    "focus_signals": focus_signals,
                    "exclusion_rules": exclusion_rules_value,
                    "location_preference": location_preference_value,
                    "linked_job_profile_id": "" if linked_job_profile_id == "不关联岗位" else linked_job_profile_id,
                    "description": description_value,
                }
                with st.spinner("正在生成寻访策略..."):
                    strategy = generate_sourcing_strategy(task_payload, use_llm=has_required_api_key())
                task_id = add_sourcing_task(**task_payload, strategy=strategy, status="待确认策略")
                st.session_state.selected_sourcing_task_id = task_id
                st.success(f"已生成寻访策略，任务 #{task_id} 等待你确认。")
                st.rerun()

        st.markdown("")
        with st.container(border=True):
            st.markdown("""
            <div class="sourcing-card-title"><span class="sourcing-card-icon">2</span>策略确认</div>
            <div class="sourcing-card-sub">审核系统生成的人才画像、关键词、数据源、搜索 Query 与风险提示。</div>
            """, unsafe_allow_html=True)
            section_label("Strategy review")
            pending_sourcing_success = st.session_state.pop("pending_sourcing_success", "")
            if pending_sourcing_success:
                st.success(pending_sourcing_success)
            tasks = list_sourcing_tasks(limit=50)
            if not tasks:
                st.info("还没有寻访任务。先在左侧创建任务，系统会生成关键词、数据源和搜索 Query。")
            else:
                default_task_id = st.session_state.get("selected_sourcing_task_id", tasks[0]["id"])
                task_labels = [f"#{t['id']} · {t['task_name']} · {t['status']}" for t in tasks]
                task_ids = [t["id"] for t in tasks]
                task_index = task_ids.index(default_task_id) if default_task_id in task_ids else 0
                selected_label = st.selectbox("选择寻访任务", task_labels, index=task_index, key="src_task_selector")
                selected_task_id = task_ids[task_labels.index(selected_label)]
                st.session_state.selected_sourcing_task_id = selected_task_id
                selected_task = get_sourcing_task(selected_task_id)
                strategy = selected_task.get("strategy_json", {}) if selected_task else {}

                if selected_task:
                    st.markdown(
                        f"""
                        <div class="strategy-status">
                          <div>
                            <div class="strategy-status-title">{_compact_text(selected_task['task_name'], 80)}</div>
                            <div class="strategy-status-meta">
                              方向：{_compact_text(selected_task['talent_direction'], 24)} ·
                              级别：{_compact_text(selected_task['target_level'], 24)} ·
                              场景：{_compact_text(selected_task['business_scene'], 90)}
                            </div>
                          </div>
                          <div class="strategy-status-pill">{_compact_text(selected_task['status'], 18)}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if selected_task.get("description"):
                        st.caption(_compact_text(selected_task["description"], 180))

                if strategy:
                    profile_summary = strategy.get("profile_summary", {})
                    summary_cards = ""
                    for label, value in list(profile_summary.items())[:6]:
                        summary_cards += f"""
                        <div class="strategy-mini-card">
                          <div class="strategy-mini-label">{_compact_text(label, 24)}</div>
                          <div class="strategy-mini-value">{_compact_text(value, 100)}</div>
                        </div>
                        """
                    if summary_cards:
                        st.markdown(
                            f"""
                            <div class="strategy-block">
                              <div class="strategy-block-title">结构化人才画像</div>
                              <div class="strategy-mini-grid">{summary_cards}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    keywords = strategy.get("core_keywords", []) + strategy.get("expanded_keywords", [])
                    if keywords:
                        st.markdown(
                            f"""
                            <div class="strategy-block">
                              <div class="strategy-block-title">核心关键词与扩展词</div>
                              {_skill_tags(keywords, max_show=28)}
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    strategy_sources = strategy.get("source_priority", [])
                    if not people_system_enabled():
                        strategy_sources = [
                            src for src in strategy_sources
                            if src not in {"内部人才库", "公司人才库"}
                        ]
                    if strategy_sources:
                        source_html = "".join(
                            f'<span class="strategy-source-pill">{_compact_text(src, 30)}</span>'
                            for src in strategy_sources
                        )
                        st.markdown(
                            f"""
                            <div class="strategy-block">
                              <div class="strategy-block-title">推荐数据源</div>
                              <div class="strategy-source-list">{source_html}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )
                    if not people_system_enabled():
                        st.caption("公司人才库尚未接入，本次策略不会调用内部候选人数据。")

                    search_queries = strategy.get("search_queries", [])
                    if search_queries:
                        st.markdown('<div class="strategy-block"><div class="strategy-block-title">搜索 Query</div>', unsafe_allow_html=True)
                        for q in search_queries[:4]:
                            st.code(q)
                        st.markdown("</div>", unsafe_allow_html=True)

                    scoring_dimensions = strategy.get("scoring_dimensions", [])
                    if scoring_dimensions:
                        with st.expander("查看评分维度", expanded=False):
                            st.dataframe(pd.DataFrame(scoring_dimensions), use_container_width=True, hide_index=True)

                    risk_notes = strategy.get("risk_notes", [])
                    if risk_notes:
                        risk_html = "".join(
                            f"<li>{_compact_text(note, 130)}</li>"
                            for note in risk_notes[:6]
                        )
                        st.markdown(
                            f"""
                            <div class="strategy-block">
                              <div class="strategy-block-title">风险提示</div>
                              <ul class="strategy-risk-list">{risk_html}</ul>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                    if selected_task.get("status") == "待确认策略":
                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("确认策略，进入寻访", type="primary", use_container_width=True, key=f"confirm_strategy_{selected_task_id}"):
                                update_sourcing_task_strategy(selected_task_id, strategy, status="待寻访")
                                st.session_state.pending_sourcing_success = "策略已确认。请继续在“生成候选线索”卡片中选择数据源并启动寻访。"
                                st.rerun()
                        with b2:
                            if st.button("重新生成策略", use_container_width=True, key=f"regen_strategy_{selected_task_id}"):
                                with st.spinner("正在重新生成寻访策略..."):
                                    new_strategy = generate_sourcing_strategy(selected_task, use_llm=has_required_api_key())
                                update_sourcing_task_strategy(selected_task_id, new_strategy, status="待确认策略")
                                st.session_state.pending_sourcing_success = "已重新生成策略，请再次确认。"
                                st.rerun()
                    else:
                        st.info("该策略已确认，可以在下方“生成候选线索”卡片中选择数据源并生成候选卡片。")
                        if st.button("重新生成策略", use_container_width=True, key=f"regen_strategy_{selected_task_id}"):
                            with st.spinner("正在重新生成寻访策略..."):
                                new_strategy = generate_sourcing_strategy(selected_task, use_llm=has_required_api_key())
                            update_sourcing_task_strategy(selected_task_id, new_strategy, status="待确认策略")
                            st.session_state.pending_sourcing_success = "已重新生成策略，请再次确认。"
                            st.rerun()

    if sourcing_sub_view == "2. 候选线索核验":
        st.markdown("")
        with st.container(border=True):
            st.markdown("""
            <div class="sourcing-card-title"><span class="sourcing-card-icon">3</span>生成候选线索</div>
            <div class="sourcing-card-sub">选择已确认任务、匹配 Skill 和公开数据源，生成候选人卡片。</div>
            """, unsafe_allow_html=True)
            section_label("Sourcing APIs to candidate cards")
            tasks = list_sourcing_tasks(limit=100)
            if not tasks:
                st.info("请先创建并确认一个寻访任务。")
            else:
                task_labels = [f"#{t['id']} · {t['task_name']} · {t['status']}" for t in tasks]
                task_ids = [t["id"] for t in tasks]
                selected_task_id = st.session_state.get("selected_sourcing_task_id", task_ids[0])
                task_index = task_ids.index(selected_task_id) if selected_task_id in task_ids else 0
                lead_task_label = st.selectbox("选择寻访任务", task_labels, index=task_index, key="lead_task_selector")
                lead_task_id = task_ids[task_labels.index(lead_task_label)]
                lead_task = get_sourcing_task(lead_task_id)
                st.session_state.selected_sourcing_task_id = lead_task_id

                if lead_task and lead_task["status"] == "待确认策略":
                    st.warning("这个任务的寻访策略还没有确认。建议先在上方“策略确认”卡片中确认策略，再生成候选线索。")
                if lead_task:
                    current_candidates = list_sourcing_candidates(task_id=lead_task_id, limit=1000)
                    status_counts = {}
                    for candidate in current_candidates:
                        status = candidate.get("decision_status") or "待确认"
                        status_counts[status] = status_counts.get(status, 0) + 1
                    p1, p2, p3, p4 = st.columns(4)
                    p1.metric("当前任务线索", len(current_candidates))
                    p2.metric("待确认", status_counts.get("待确认", 0))
                    p3.metric("重点关注", status_counts.get("重点关注", 0))
                    p4.metric("已入库", status_counts.get("已入库", 0))

                settings_col1, settings_col2 = st.columns([1, 1.4])
                with settings_col1:
                    lead_hiring_type = st.selectbox(
                        "招聘类型 / 匹配 Skill",
                        ["社招", "校招"],
                        key="lead_hiring_type",
                    )
                    lead_matching_skill = active_matching_skill("开发", lead_hiring_type)
                    st.caption(f"将使用：{lead_matching_skill['skill_name']} · {lead_matching_skill.get('focus_summary', '')}")
                    per_source_limit = st.slider(
                        "每个数据源最多生成",
                        min_value=3,
                        max_value=20,
                        value=10,
                        step=1,
                        key="lead_per_source_limit",
                    )
                with settings_col2:
                    st.markdown(_sourcing_source_readiness_cards(), unsafe_allow_html=True)
                    source_options = ["GitHub API", "arXiv API", "Google Scholar API"]
                    if people_system_enabled():
                        source_options.insert(0, "公司人才库（People API）")
                    source_defaults = [
                        source for source in ["公司人才库（People API）", "GitHub API", "arXiv API"]
                        if source in source_options
                    ]
                    if "lead_sources" in st.session_state:
                        valid_sources = [
                            source for source in st.session_state.lead_sources
                            if source in source_options
                        ]
                        st.session_state.lead_sources = valid_sources or source_defaults
                    lead_sources = st.multiselect(
                        "寻访数据源",
                        source_options,
                        default=source_defaults,
                        key="lead_sources",
                    )
                    if people_system_enabled():
                        st.caption("公司人才库已接入；外部默认数据源为 GitHub、arXiv。")
                    else:
                        st.caption("公司人才库：未接入。当前仅使用 GitHub、arXiv 等外部公开数据源。")

                c1, c2 = st.columns([1, 2])
                with c1:
                    if st.button("生成候选人卡片", type="primary", use_container_width=True, key="extract_leads"):
                        generated_leads = []
                        source_run_rows = []
                        if "公司人才库（People API）" in lead_sources:
                            with st.spinner("正在从公司 People 系统中匹配候选人..."):
                                people_leads = generate_candidates_from_people_system(
                                    lead_task, lead_matching_skill, limit=per_source_limit
                                )
                                generated_leads.extend(people_leads)
                                source_run_rows.append({"数据源": "People API", "生成线索": len(people_leads), "状态": "已完成"})
                        if "GitHub API" in lead_sources:
                            with st.spinner("正在通过 GitHub API 搜索公开项目..."):
                                github_leads = generate_candidates_from_github_api(
                                    lead_task, lead_matching_skill, limit=per_source_limit
                                )
                                generated_leads.extend(github_leads)
                                source_run_rows.append({"数据源": "GitHub API", "生成线索": len(github_leads), "状态": "已完成"})
                        if "arXiv API" in lead_sources:
                            with st.spinner("正在通过 arXiv API 搜索论文作者..."):
                                arxiv_leads = generate_candidates_from_arxiv_api(
                                    lead_task, lead_matching_skill, limit=per_source_limit
                                )
                                generated_leads.extend(arxiv_leads)
                                source_run_rows.append({"数据源": "arXiv API", "生成线索": len(arxiv_leads), "状态": "已完成"})
                        if "Google Scholar API" in lead_sources:
                            scholar_providers = configured_google_scholar_provider_names()
                            if not scholar_providers:
                                st.warning("已选择 Google Scholar，但未配置可用服务商 Key；本次已跳过。支持 SERPAPI_API_KEY、SERPDOG_API_KEY 或 SCRAPINGBEE_API_KEY。")
                                source_run_rows.append({"数据源": "Google Scholar API", "生成线索": 0, "状态": "未配置，已跳过"})
                            else:
                                with st.spinner(f"正在通过 {scholar_providers[0]} 查询 Google Scholar..."):
                                    scholar_leads = generate_candidates_from_google_scholar_api(
                                        lead_task, lead_matching_skill, limit=per_source_limit
                                    )
                                    generated_leads.extend(scholar_leads)
                                    source_run_rows.append({"数据源": f"Google Scholar · {scholar_providers[0]}", "生成线索": len(scholar_leads), "状态": "已完成"})

                        if not generated_leads:
                            if source_run_rows:
                                st.dataframe(pd.DataFrame(source_run_rows), use_container_width=True, hide_index=True)
                            st.error("没有生成候选线索。请检查已选择的数据源、API Key、网络或限流状态。")
                        else:
                            with st.spinner("正在按匹配 Skill 生成候选线索评分..."):
                                scored_leads = score_sourcing_candidates(generated_leads, lead_task, lead_matching_skill)
                                saved_ids = save_candidate_leads(lead_task_id, scored_leads)
                            st.dataframe(pd.DataFrame(source_run_rows), use_container_width=True, hide_index=True)
                            st.success(f"已生成 {len(saved_ids)} 条候选线索，等待你确认。")
                            st.rerun()
                with c2:
                    st.markdown("""
                    <div class="sourcing-dashboard-note">
                      候选线索会按所选社招/校招 Skill 进行匹配度分析。外部源只调用公开 API；
                      不会绕过登录、验证码或权限墙。People API 未接入时不会展示或调用内部人才库。
                    </div>
                    """, unsafe_allow_html=True)

        st.markdown("")
        with st.container(border=True):
            st.markdown("""
            <div class="sourcing-card-title"><span class="sourcing-card-icon">4</span>候选人工作台</div>
            <div class="sourcing-card-sub">逐个核验候选人的推荐理由、履历摘要、公开证据与联系方式，再人工决定是否入库。</div>
            """, unsafe_allow_html=True)
            tasks = list_sourcing_tasks(limit=100)
            if not tasks:
                st.info("请先创建寻访任务并生成候选线索。")
            else:
                task_ids = [t["id"] for t in tasks]
                lead_task_id = st.session_state.get("selected_sourcing_task_id", task_ids[0])
                if lead_task_id not in task_ids:
                    lead_task_id = task_ids[0]
                section_label("Single candidate workspace")
                decision_filter = st.radio("线索状态", ["待确认", "重点关注", "已入库", "暂不处理", "全部"], horizontal=True, key="lead_decision_filter")
                decision_status = None if decision_filter == "全部" else decision_filter
                candidates = list_sourcing_candidates(task_id=lead_task_id, decision_status=decision_status, limit=200)
                if not candidates:
                    st.info("当前筛选条件下暂无候选线索。")
                else:
                    candidate_rows = _sourcing_candidate_export_rows(candidates)
                    with st.expander("候选线索列表与导出", expanded=True):
                        st.dataframe(
                            pd.DataFrame(candidate_rows),
                            use_container_width=True,
                            hide_index=True,
                        )
                        csv_data = pd.DataFrame(candidate_rows).to_csv(index=False).encode("utf-8-sig")
                        st.download_button(
                            "下载当前线索 CSV",
                            data=csv_data,
                            file_name=f"sourcing_candidates_task_{lead_task_id}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                            mime="text/csv",
                            use_container_width=True,
                        )
                    candidate_ids = [cand["id"] for cand in candidates]
                    selected_candidate_id = st.session_state.get("selected_sourcing_candidate_id", candidate_ids[0])
                    if selected_candidate_id not in candidate_ids:
                        selected_candidate_id = candidate_ids[0]
                        st.session_state.selected_sourcing_candidate_id = selected_candidate_id

                    current_index = candidate_ids.index(selected_candidate_id)
                    nav_prev, nav_select, nav_next, nav_count = st.columns([0.8, 3.2, 0.8, 0.8])
                    with nav_prev:
                        if st.button("上一位", use_container_width=True, disabled=current_index == 0, key="lead_prev"):
                            st.session_state.selected_sourcing_candidate_id = candidate_ids[current_index - 1]
                            st.rerun()
                    with nav_select:
                        candidate_labels = [
                            f"{cand['candidate_name']} · {cand['match_score']:.1f}/100 · {cand['recommendation_level'] or '待评估'} · {cand['decision_status']}"
                            for cand in candidates
                        ]
                        selected_label = st.selectbox("当前候选人", candidate_labels, index=current_index, key="lead_candidate_selector")
                        selected_candidate_id = candidate_ids[candidate_labels.index(selected_label)]
                        st.session_state.selected_sourcing_candidate_id = selected_candidate_id
                        current_index = candidate_ids.index(selected_candidate_id)
                    with nav_next:
                        if st.button("下一位", use_container_width=True, disabled=current_index >= len(candidate_ids) - 1, key="lead_next"):
                            st.session_state.selected_sourcing_candidate_id = candidate_ids[current_index + 1]
                            st.rerun()
                    with nav_count:
                        st.metric("序号", f"{current_index + 1}/{len(candidates)}")

                    cand = candidates[candidate_ids.index(selected_candidate_id)]
                    raw_snapshot = cand.get("raw_snapshot", {}) if isinstance(cand.get("raw_snapshot"), dict) else {}
                    skill_match = raw_snapshot.get("skill_match", {})
                    contact_channels = raw_snapshot.get("contact_channels") or []
                    source_origin_type = cand.get("source_origin_type") or raw_snapshot.get("source_origin_type") or raw_snapshot.get("source_type", "来源未确认")
                    authenticity_status = cand.get("authenticity_status") or raw_snapshot.get("authenticity_status") or "待核验"

                    st.markdown(
                        f"""
                        <div class="candidate-header">
                          <div class="candidate-header-name">{cand['candidate_name']}</div>
                          <div class="candidate-header-meta">
                            {cand.get('current_org') or '机构未确认'} · {cand.get('decision_status', '待确认')} · {source_origin_type} · {authenticity_status}
                          </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

                    left_col, main_col, right_col = st.columns([1.15, 2.05, 1.25])
                    with left_col:
                        st.markdown("**推荐判断**")
                        st.metric("匹配分", f"{cand['match_score']:.1f}/100")
                        st.caption(f"推荐等级：{cand.get('recommendation_level') or '待评估'}")
                        if skill_match:
                            st.caption(
                                f"匹配 Skill：{skill_match.get('matching_skill_name', '未指定')} · "
                                f"{skill_match.get('hiring_type', '未指定')}"
                            )
                            dim_rows = []
                            for dim in skill_match.get("dimensions", []):
                                dim_rows.append({
                                    "维度": dim.get("label", dim.get("dimension_key", "")),
                                    "权重": f"{float(dim.get('weight', 0)) * 100:.0f}%",
                                    "评分": dim.get("score", 0),
                                })
                            if dim_rows:
                                st.dataframe(pd.DataFrame(dim_rows), use_container_width=True, hide_index=True)
                        st.markdown("**推荐理由**")
                        st.write(cand.get("recommendation_reason") or "暂无")
                        if cand.get("uncertainties"):
                            st.markdown("**不确定点**")
                            for item in cand["uncertainties"]:
                                st.markdown(f"- {item}")

                    with main_col:
                        st.markdown("**候选人信息**")
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("当前状态", cand.get("decision_status", "待确认"))
                        m2.metric("来源类型", source_origin_type)
                        m3.metric("真实性", authenticity_status)
                        m4.metric("建议动作", raw_snapshot.get("suggested_action", cand.get("suggested_action", "待判断")))
                        if cand.get("direction_tags"):
                            st.markdown(_skill_tags(cand["direction_tags"], max_show=24), unsafe_allow_html=True)

                        st.markdown("**可联系渠道**")
                        if contact_channels:
                            for contact in contact_channels:
                                ctype = contact.get("type", "联系方式") if isinstance(contact, dict) else "联系方式"
                                value = contact.get("value", "") if isinstance(contact, dict) else str(contact)
                                source = contact.get("source", "未确认") if isinstance(contact, dict) else "未确认"
                                confidence = contact.get("confidence", "medium") if isinstance(contact, dict) else "low"
                                if str(value).startswith(("http://", "https://")):
                                    st.markdown(f"- `{ctype}` [{value}]({value}) · 来源：{source} · 可信度：{confidence}")
                                else:
                                    st.markdown(f"- `{ctype}` {value} · 来源：{source} · 可信度：{confidence}")
                        else:
                            st.caption("暂未获取到公开或授权联系方式。可先通过公开主页、GitHub profile、论文主页或 People 系统进一步确认。")

                        st.markdown("**简历 / 履历摘要**")
                        resume_text = (
                            raw_snapshot.get("resume_text")
                            or raw_snapshot.get("profile_summary")
                            or raw_snapshot.get("work_summary")
                            or raw_snapshot.get("recommendation_reason")
                        )
                        if resume_text:
                            st.write(resume_text)
                        else:
                            st.info("暂无完整简历，仅基于公开资料、论文/开源证据，或已接入的公司 People 系统摘要生成。")

                        evidence_summaries = []
                        for ev in cand.get("evidence_links") or []:
                            if isinstance(ev, dict) and ev.get("summary"):
                                evidence_summaries.append(ev["summary"])
                        if evidence_summaries:
                            st.markdown("**项目 / 论文 / 公开贡献摘要**")
                            for summary in evidence_summaries[:4]:
                                st.markdown(f"- {summary}")

                    with right_col:
                        st.markdown("**公开来源与证据**")
                        evidence_links = cand.get("evidence_links") or []
                        if evidence_links:
                            for ev_index, ev in enumerate(evidence_links, start=1):
                                title = ev.get("title", "公开证据") if isinstance(ev, dict) else str(ev)
                                url = ev.get("url", "") if isinstance(ev, dict) else ""
                                etype = ev.get("evidence_type", "公开资料") if isinstance(ev, dict) else "公开资料"
                                summary = ev.get("summary", "") if isinstance(ev, dict) else ""
                                st.markdown(f"**{ev_index}. {title}**")
                                st.caption(f"类型：{etype}")
                                if url:
                                    st.markdown(f"[查看来源]({url})")
                                if summary:
                                    st.write(summary)
                        else:
                            st.info("暂无可展示的公开证据。")

                    st.divider()
                    hr_note = st.text_area("HR 备注", value=cand.get("hr_note", ""), key=f"lead_note_{cand['id']}", height=90)
                    a1, a2, a3 = st.columns(3)
                    with a1:
                        if st.button("确认加入人才库", type="primary", use_container_width=True, key=f"lead_add_{cand['id']}"):
                            talent_id = confirm_sourcing_candidate_to_pool(cand["id"], hr_note=hr_note)
                            st.success(f"已加入开源人才库：#{talent_id}")
                            st.rerun()
                    with a2:
                        if st.button("标记重点关注", use_container_width=True, key=f"lead_focus_{cand['id']}"):
                            mark_sourcing_candidate(cand["id"], "重点关注", hr_note=hr_note)
                            st.success("已标记为重点关注。")
                            st.rerun()
                    with a3:
                        if st.button("暂不处理", use_container_width=True, key=f"lead_reject_{cand['id']}"):
                            mark_sourcing_candidate(cand["id"], "暂不处理", hr_note=hr_note)
                            st.info("已标记为暂不处理。")
                            st.rerun()

    if sourcing_sub_view == "3. 开源人才库沉淀":
        st.markdown("")
        with st.container(border=True):
            st.markdown("""
            <div class="sourcing-card-title"><span class="sourcing-card-icon">5</span>已入库人才库与方法参考</div>
            <div class="sourcing-card-sub">确认入库的人选统一沉淀在这里；下方保留筛选、检索与导出能力。</div>
            """, unsafe_allow_html=True)
            r1, r2, r3 = st.columns(3)
            with r1:
                st.markdown("""
                <div class="method-card">
                  <div class="method-card-title">岗位能力要求与评估标准</div>
                  <div class="method-card-sub">复用岗位 JD 与社招/校招 Skill，保证寻访口径和简历筛选一致。</div>
                </div>""", unsafe_allow_html=True)
            with r2:
                st.markdown("""
                <div class="method-card">
                  <div class="method-card-title">行业人才分布与趋势</div>
                  <div class="method-card-sub">从 GitHub、arXiv 等公开 API 提取证据，不调用未接入的内部人才库。</div>
                </div>""", unsafe_allow_html=True)
            with r3:
                st.markdown("""
                <div class="method-card">
                  <div class="method-card-title">开源人才工作方法论</div>
                  <div class="method-card-sub">AI 负责检索、评分和摘要，入库与联系动作始终由 HR 人工确认。</div>
                </div>""", unsafe_allow_html=True)
            st.markdown("""
            <div style="font-size:1rem;font-weight:600;color:#1c2a22;margin-bottom:4px">开源人才库</div>
            <div style="font-size:12px;color:#718078;margin-bottom:14px">
              只展示已经进入人才库的人选；开源寻访线索必须由你确认后才会写入这里。
            </div>
            """, unsafe_allow_html=True)

            # Filters
            section_label("Search & Filters")
            f1, f2, f3, f4 = st.columns([2,1,1,1])
            with f1:
                kw = st.text_input("", placeholder="🔎  Keyword search (name, skills, projects...)", key="tp_kw", label_visibility="collapsed")
            with f2:
                dom_opts = ["All Domains"] + sorted(d for d in ts["by_domain"].keys() if d)
                dom_sel = st.selectbox("", dom_opts, key="tp_dom", label_visibility="collapsed")
            with f3:
                status_opts = ["All", TalentPoolStatus.ACTIVE.value, TalentPoolStatus.PLACED.value, TalentPoolStatus.ARCHIVED.value]
                st_sel = st.selectbox("", status_opts, key="tp_status", label_visibility="collapsed")
            with f4:
                remote_only = st.checkbox("🌍 Remote friendly only", value=False, key="tp_remote")

            f5, f6, f7, f8 = st.columns([1,1,1,1])
            with f5:
                min_exp = st.slider("Min experience (years)", 0, 15, 0, key="tp_minx")
            with f6:
                max_exp = st.slider("Max experience (years)", 0, 20, 20, key="tp_maxx")
            with f7:
                skill = st.text_input("Skill must include", placeholder="e.g. Python, React, AWS", key="tp_skill", label_visibility="collapsed")
            with f8:
                sort_by = st.selectbox("", ["Recently updated","Most experienced","Highest availability"],
                                       key="tp_sort", label_visibility="collapsed")

            # Run search
            search_status = None
            if st_sel != "All":
                search_status = TalentPoolStatus(st_sel)
            domain_q = None if dom_sel == "All Domains" else dom_sel
            results = search_talents(
                keyword=kw or None,
                domain=domain_q,
                status=search_status,
                min_experience=min_exp if min_exp > 0 else None,
                max_experience=max_exp if max_exp < 20 else None,
                skill=skill or None,
                remote_only=remote_only,
                limit=300,
            )

            if sort_by == "Most experienced":
                results.sort(key=lambda r: r.total_experience_years, reverse=True)
            elif sort_by == "Highest availability":
                order = {TalentPoolStatus.ACTIVE: 0, TalentPoolStatus.PLACED: 1, TalentPoolStatus.ARCHIVED: 2}
                results.sort(key=lambda r: (order.get(r.status, 3), -r.total_experience_years))

            st.info(f"🔎 Found {len(results)} matching talent profiles")

            # Skill cloud
            if results:
                all_skills = []
                for r in results: all_skills.extend(r.skills)
                sc = sorted(set(all_skills))
                if sc:
                    with st.expander(f"🏷️  Skill index ({len(sc)} unique skills across results)", expanded=False):
                        st.markdown(_skill_tags(sc, max_show=min(100, len(sc))), unsafe_allow_html=True)

            if len(results) == 0:
                st.markdown("""
                <div style="text-align:center;padding:40px 20px">
                  <div style="font-size:40px;margin-bottom:12px">📭</div>
                  <div style="font-size:15px;font-weight:600;color:#1c2a22;margin-bottom:4px">No matching talent found</div>
                  <div style="font-size:12px;color:#718078">Try relaxing filters, or confirm sourcing leads into the talent pool.
                  <br>If you haven't yet, click "Generate sample data" in the sidebar to seed demo profiles.</div>
                </div>""", unsafe_allow_html=True)

            # Grid of cards
            col_cards = st.columns(2, gap="medium")
            for idx, r in enumerate(results[:60]):
                card = generate_open_resume_card(r, anonymize=True)
                stat_color = {"Active": "#30b86a", "Placed": "#36c873", "Archived": "#718078"}.get(card["availability"], "#718078")

                html = f"""
                <div class="tp-card">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;margin-bottom:4px">
                    <div>
                      <div class="tp-card-title">👤 {card['display_name']}</div>
                      <div class="tp-card-headline">{card['headline']}</div>
                    </div>
                    <span style="display:inline-flex;align-items:center;padding:3px 10px;border-radius:20px;
                      font-size:11px;font-weight:500;background:rgba(48,54,61,0.3);color:{stat_color};
                      border:1px solid rgba(48,54,61,0.8);flex-shrink:0">● {card['availability']}</span>
                  </div>

                  <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
                    <span class="skill-tag" style="background:rgba(163,113,247,0.08);color:#8b5cf6;border-color:rgba(163,113,247,0.2)">📍 {card['location']}</span>
                    <span class="skill-tag" style="background:rgba(35,134,54,0.08);color:#30b86a;border-color:rgba(35,134,54,0.2)">💼 {card['experience_level']}</span>
                    {'<span class="skill-tag" style="background:rgba(31,111,235,0.08);color:#4f8ff7;border-color:rgba(31,111,235,0.2)">🌍 Open to remote</span>' if card['open_to_remote'] else ''}
                  </div>

                  <div style="margin-bottom:8px">
                    <div style="font-size:10px;color:#98a49d;letter-spacing:0.06em;
                                text-transform:uppercase;font-family:'JetBrains Mono',monospace;margin-bottom:5px">Top Skills</div>
                    {_skill_tags(card['skills'], max_show=8)}
                  </div>

                  {f'<div style="margin-bottom:8px"><div style="font-size:10px;color:#98a49d;letter-spacing:0.06em;text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:5px">Education</div><div style="font-size:11px;color:#718078;line-height:1.5">{"<br>".join(card["education"][:2]) or "—"}</div></div>' if card['education'] else ''}

                  {card['certifications'] and f'<div style="margin-bottom:8px"><div style="font-size:10px;color:#98a49d;letter-spacing:0.06em;text-transform:uppercase;font-family:JetBrains Mono,monospace;margin-bottom:5px">Certifications</div>{_skill_tags(card["certifications"], max_show=3)}</div>' or ''}

                  <div style="padding-top:8px;border-top:1px solid #e4ebe5;margin-top:8px;
                              display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:10px;color:#98a49d;font-family:'JetBrains Mono',monospace">Updated {card['updated_at']}</span>
                    <span style="font-size:10px;color:#36c873;font-weight:500">ID #{card['id']}</span>
                  </div>
                </div>
                """
                with col_cards[idx % 2]:
                    st.markdown(html, unsafe_allow_html=True)

            # Export
            st.divider()
            ex1, ex2, ex3 = st.columns(3)
            with ex1:
                if st.button("📤 Export open resumes (JSON)", use_container_width=True):
                    data = json.dumps(export_talent_pool_json(anonymize=True, records=results),
                                      indent=2, ensure_ascii=False).encode("utf-8")
                    st.download_button("↓ Download talent_pool.json", data=data,
                        file_name=f"talent_pool_{datetime.now().strftime('%Y%m%d')}.json",
                        mime="application/json", use_container_width=True)
            with ex2:
                if results and st.button("📊 View distribution chart", use_container_width=True):
                    # Domain distribution bar
                    dcounts = {}
                    for r in results:
                        k = r.domain or "Unspecified"
                        dcounts[k] = dcounts.get(k, 0) + 1
                    if dcounts:
                        fig = go.Figure(go.Bar(
                            x=list(dcounts.values()),
                            y=list(dcounts.keys()),
                            orientation="h",
                            marker=dict(color="#36c873", line=dict(width=0)),
                            text=list(dcounts.values()), textposition="outside",
                        ))
                        fig.update_layout(title="Talent by Domain", title_x=0.02,
                            title_font=dict(size=13, color="#1c2a22"))
                        _plotly_dark(fig, height=360)
                        st.plotly_chart(fig, use_container_width=True)
            with ex3:
                # Skill cloud via horizontal bar for top 20
                top_skills = get_skill_cloud(20)
                if top_skills and st.button("🏷️  Top skills across pool", use_container_width=True):
                    sk, sv = zip(*reversed(top_skills))
                    fig = go.Figure(go.Bar(x=sv, y=sk, orientation="h",
                        marker=dict(color=list(reversed(["#36c873","#4f8ff7","#30b86a","#8b5cf6","#d4a72c","#f85149"]*4))[:len(sk)]),
                        text=sv, textposition="outside",
                    ))
                    fig.update_layout(title="Top 20 Skills in Pool", title_x=0.02,
                        title_font=dict(size=13, color="#1c2a22"))
                    _plotly_dark(fig, height=520)
                    st.plotly_chart(fig, use_container_width=True)

st.markdown(f"""
<div style="margin-top:3rem;padding-top:16px;border-top:1px solid #e4ebe5;
            display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;
            font-size:11px;color:#98a49d;font-family:JetBrains Mono,monospace">
  <span>TalentOS · HR Intelligence Platform</span>
  <span>{provider_label()} · Pydantic v2 · SQLite · Streamlit</span>
  <span>{datetime.now().strftime("%d %b %Y, %H:%M")}</span>
</div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# Removed module: Recruitment Data Review
# ═══════════════════════════════════════════════════════════════════════════════
if False:
    st.markdown("""
    <div style="display:flex;align-items:center;justify-content:space-between;
                flex-wrap:wrap;gap:8px;margin-bottom:14px">
      <div>
        <div style="font-size:1.1rem;font-weight:600;color:#1c2a22">📊 Recruitment Data Review</div>
        <div style="font-size:12px;color:#718078;margin-top:2px">
          Funnel analysis, time-to-hire metrics, trend tracking, source effectiveness, and actionable insights.
        </div>
      </div>
      <div style="display:flex;gap:6px">
    """ + badge_html("Funnel KPIs","blue") + badge_html("Trends","amber") + badge_html("Insights","purple") + """
      </div>
    </div>""", unsafe_allow_html=True)

    # Date range + filters
    section_label("Date range & filters")
    today = date.today()
    f1, f2, f3 = st.columns([1,1,2])
    with f1:
        from_d = st.date_input("From", today - timedelta(days=180), key="an_from")
    with f2:
        to_d = st.date_input("To", today, key="an_to")
    with f3:
        # Quick date presets
        _, p1, p2, p3, p4 = st.columns([1,1,1,1,1])
        with p1:
            if st.button("7D", use_container_width=True, key="p7"):
                from_d = today - timedelta(days=7)
        with p2:
            if st.button("30D", use_container_width=True, key="p30"):
                from_d = today - timedelta(days=30)
        with p3:
            if st.button("90D", use_container_width=True, key="p90"):
                from_d = today - timedelta(days=90)
        with p4:
            if st.button("ALL", use_container_width=True, key="pall"):
                from_d = date(2020,1,1)

    # Snapshot KPIs
    summary = overall_summary(from_d, to_d)
    m1,m2,m3,m4,m5,m6 = st.columns(6)
    m1.markdown(_kpi("APPLICANTS", summary['applied'],
        sub=f"screen rate {summary['screen_rate']}%", color="#36c873"), unsafe_allow_html=True)
    m2.markdown(_kpi("SCREENED", summary['screened'],
        sub=f"interview rate {summary['interview_rate']}%", color="#4f8ff7"), unsafe_allow_html=True)
    m3.markdown(_kpi("INTERVIEWED", summary['interviewed'],
        sub=f"offer rate {summary['offer_rate']}%", color="#d4a72c"), unsafe_allow_html=True)
    m4.markdown(_kpi("HIRED", summary['hired'],
        sub=f"accept {summary['accept_rate']}%", color="#30b86a"), unsafe_allow_html=True)
    m5.markdown(_kpi("HIRE RATE", f"{summary['overall_hire_rate']}%",
        sub="overall", color="#8b5cf6"), unsafe_allow_html=True)
    tth = summary['avg_days_to_hire']
    tth_color = "#30b86a" if tth and tth < 30 else "#d4a72c" if tth else "#718078"
    m6.markdown(_kpi("AVG TTH", f"{tth}d" if tth else "—",
        sub="avg time to hire", color=tth_color), unsafe_allow_html=True)

    st.divider()

    # Insight cards
    insights = generate_insights()
    if insights:
        section_label("💡 Actionable insights")
        for ins in insights[:4]:
            st.markdown(_insight_html(ins["severity"], ins["title"], ins["detail"]), unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # Row 1: Funnel + Monthly trend
    r1c1, r1c2 = st.columns([1, 1.4])
    with r1c1:
        section_label("🎯 Hiring Funnel")
        fd = funnel_data_for_chart(from_d, to_d)
        if sum(fd["values"]) > 0:
            fig = go.Figure(go.Funnel(
                y=fd["labels"], x=fd["values"],
                textposition="inside",
                textinfo="value+percent previous",
                opacity=0.85,
                marker=dict(
                    color=["#36c873","#4f8ff7","#d4a72c","#8b5cf6","#30b86a"],
                    line=dict(width=0)
                ),
                connector=dict(line=dict(color="#e4ebe5", width=1)),
            ))
            fig.update_layout(
                title=dict(text="Applicant → Hired conversion", x=0.02,
                    font=dict(size=13, color="#1c2a22")),
            )
            _plotly_dark(fig, height=400)
            st.plotly_chart(fig, use_container_width=True)

            # Drop-off summary
            with st.expander("📉 Stage drop-off"):
                for i, (s, e) in enumerate(zip(fd["labels"][:-1], fd["labels"][1:])):
                    do = fd["dropoffs_pct"][i]
                    sc = "#30b86a" if do < 25 else "#d4a72c" if do < 45 else "#f85149"
                    st.markdown(
                        f'<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #e4ebe5">'
                        f'<span style="font-size:12px;color:#718078">{s} → {e}</span>'
                        f'<span style="font-size:12px;font-weight:600;color:{sc}">Drop-off {do}%</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
        else:
            st.info("No screening records found in this range. Try generating sample data in the sidebar or run a screening.")

    with r1c2:
        section_label("📈 Monthly Trend")
        months = 6
        trend = monthly_trend(months)
        if trend:
            months_labels = [t["month"] for t in trend]
            applied_v = [t["applied"] for t in trend]
            screened_v = [t["screened"] for t in trend]
            interviewed_v = [t["interviewed"] for t in trend]
            hired_v = [t["hired"] for t in trend]

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=months_labels, y=applied_v, mode="lines+markers",
                name="Applied", line=dict(width=2.5, color="#36c873"),
                marker=dict(size=6)))
            fig.add_trace(go.Scatter(x=months_labels, y=screened_v, mode="lines+markers",
                name="Screened", line=dict(width=2.5, color="#4f8ff7"),
                marker=dict(size=6)))
            fig.add_trace(go.Scatter(x=months_labels, y=interviewed_v, mode="lines+markers",
                name="Interviewed", line=dict(width=2.5, color="#d4a72c"),
                marker=dict(size=6)))
            fig.add_trace(go.Scatter(x=months_labels, y=hired_v, mode="lines+markers",
                name="Hired", line=dict(width=2.5, color="#30b86a"),
                marker=dict(size=6), fill="tozeroy", opacity=0.5))
            fig.update_layout(
                title=dict(text=f"Pipeline trend — last {len(trend)} months", x=0.02,
                    font=dict(size=13, color="#1c2a22")),
                legend=dict(orientation="h", yanchor="top", y=1.1, x=0),
            )
            _plotly_dark(fig, height=400)
            st.plotly_chart(fig, use_container_width=True)

    # Row 2: Time metrics + Domain breakdown
    r2c1, r2c2 = st.columns([1, 1])
    with r2c1:
        section_label("⏱️  Time-to-X Metrics")
        tm_labels = ["Days to Screen", "Days to Interview", "Days to Offer", "Days to Hire"]
        tm_vals = [summary['avg_days_to_screen'], summary['avg_days_to_interview'],
                   summary['avg_days_to_offer'], summary['avg_days_to_hire']]
        tm_valid = [v if v is not None else 0 for v in tm_vals]
        tm_colors = ["#36c873","#4f8ff7","#d4a72c","#30b86a"]

        if any(tm_valid):
            fig = go.Figure(go.Bar(
                x=tm_labels, y=tm_valid,
                marker=dict(color=tm_colors, line=dict(width=0)),
                text=[f"{v}d" if v else "N/A" for v in tm_vals],
                textposition="outside",
                textfont=dict(color="#1c2a22", size=12),
            ))
            fig.add_hline(y=30, line_dash="dash", line_color="#718078",
                          annotation_text="Industry TTH benchmark (30d)",
                          annotation_position="bottom right")
            fig.update_layout(
                title=dict(text="Average days per stage", x=0.02,
                    font=dict(size=13, color="#1c2a22")),
                yaxis_title="Days",
                bargap=0.35,
            )
            _plotly_dark(fig, height=360)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No timing data yet. Records need explicit screened/interviewed/offered/hired dates.")

    with r2c2:
        section_label("🏢 Domain Breakdown")
        db = domains()
        if db:
            d_labels = [d["domain"][:22] for d in db]
            d_apps = [d["applicants"] for d in db]
            d_rates = [d["hire_rate"] for d in db]
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=d_labels, y=d_apps, name="Applicants",
                marker_color="#36c873", opacity=0.85), secondary_y=False)
            fig.add_trace(go.Scatter(x=d_labels, y=d_rates, name="Hire %",
                mode="lines+markers", line_color="#30b86a", line_width=2.5), secondary_y=True)
            fig.update_layout(
                title=dict(text="Applicants vs hire rate by domain", x=0.02,
                    font=dict(size=13, color="#1c2a22")),
                legend=dict(orientation="h", yanchor="top", y=1.1, x=0),
                bargap=0.3,
            )
            fig.update_yaxes(title_text="Applicants", secondary_y=False)
            fig.update_yaxes(title_text="Hire rate (%)", secondary_y=True, rangemode="tozero")
            _plotly_dark(fig, height=360)
            st.plotly_chart(fig, use_container_width=True)

    # Row 3: Source effectiveness + Rejection reasons + Score distribution
    r3c1, r3c2, r3c3 = st.columns(3)
    with r3c1:
        section_label("🎣 Source Effectiveness")
        src = sources(8)
        if src:
            s_labels = [s["source"] for s in src]
            s_hired = [s["hired"] for s in src]
            s_conv = [s["conversion_rate"] for s in src]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=s_labels, y=s_conv,
                marker_color=["#30b86a" if c > 10 else "#36c873" for c in s_conv],
                text=[f"{c}%" for c in s_conv], textposition="outside",
            ))
            fig.update_layout(
                title=dict(text="Hire conversion % per source", x=0.02,
                    font=dict(size=13, color="#1c2a22")),
                yaxis_title="Conversion (%)",
            )
            _plotly_dark(fig, height=380)
            st.plotly_chart(fig, use_container_width=True)
            with st.expander("Source details"):
                for s in src:
                    st.markdown(
                        f'<div style="padding:5px 0;border-bottom:1px solid #e4ebe5;display:flex;justify-content:space-between">'
                        f'<span style="font-size:12px;color:#34483b">{s["source"]}</span>'
                        f'<span style="font-size:12px;color:#718078">{s["total"]} apps · {s["hired"]} hires · <b style="color:#30b86a">{s["conversion_rate"]}%</b></span>'
                        f'</div>', unsafe_allow_html=True
                    )

    with r3c2:
        section_label("❌ Top Rejection Reasons")
        rej = rejections(10)
        if rej:
            r_labels, r_vals = zip(*rej)
            fig = go.Figure(go.Bar(
                x=r_vals, y=r_labels, orientation="h",
                marker=dict(color=["#f85149","#d4a72c","#d29922","#36c873","#8b5cf6","#4f8ff7","#30b86a","#718078","#98a49d","#d5dfd7"]),
                text=r_vals, textposition="outside",
            ))
            fig.update_layout(
                title=dict(text="Why candidates don't proceed", x=0.02,
                    font=dict(size=13, color="#1c2a22")),
            )
            _plotly_dark(fig, height=380)
            st.plotly_chart(fig, use_container_width=True)

    with r3c3:
        section_label("📶 Score Distribution")
        sh = score_histogram(10)
        if sh:
            centers = [(d["low"] + d["high"]) / 2 for d in sh]
            counts = [d["count"] for d in sh]
            colors = ["#f85149" if c < 5 else "#d4a72c" if c < 7 else "#30b86a" for c in centers]
            fig = go.Figure(go.Bar(
                x=[d["range"] for d in sh], y=counts,
                marker=dict(color=colors, line=dict(width=0)),
                text=counts, textposition="outside",
            ))
            fig.add_vline(x=4.5, line_dash="dash", line_color="#f85149", opacity=0.5)
            fig.add_vline(x=6.5, line_dash="dash", line_color="#d4a72c", opacity=0.5)
            fig.add_vline(x=8.0, line_dash="dash", line_color="#30b86a", opacity=0.5)
            fig.update_layout(
                title=dict(text="Final screening score (0–10)", x=0.02,
                    font=dict(size=13, color="#1c2a22")),
                yaxis_title="Candidates",
                bargap=0.2,
            )
            _plotly_dark(fig, height=380)
            st.plotly_chart(fig, use_container_width=True)

    # Row 4: Open jobs table
    section_label("💼 Open jobs — progress tracker")
    jobs = open_jobs()
    if jobs:
        rows = []
        for j in jobs:
            stat_c = {"Open":"#36c873","Closed":"#718078"}.get(j["status"],"#718078")
            pct = j["progress_pct"]
            pbar_c = "#30b86a" if pct >= 100 else "#36c873" if pct >= 50 else "#d4a72c"
            rows.append({
                "Title": j["job_title"],
                "Domain": j["domain"],
                "Level": j["seniority"],
                "Days": j["days_open"],
                "Applicants": j["applicants"],
                "Hired/Target": f"{j['hired']}/{j['target']}",
                "Progress": pct,
                "Status": j["status"],
            })
        df = pd.DataFrame(rows)
        # Custom styled table via HTML
        tbl_html = """
        <div style="background:#ffffff;border:1px solid #e4ebe5;border-radius:12px;overflow:hidden">
          <table style="width:100%;border-collapse:collapse">
            <thead>
              <tr style="border-bottom:1px solid #e4ebe5;background:#f5f8f4">
        """
        cols = ["Title","Domain","Level","Days","Applicants","Hired/Target","Progress","Status"]
        for c in cols:
            tbl_html += f'<th style="padding:11px 14px;text-align:left;font-size:10px;color:#98a49d;font-family:JetBrains Mono,monospace;letter-spacing:0.06em;text-transform:uppercase;font-weight:500">{c}</th>'
        tbl_html += "</tr></thead><tbody>"
        for r in rows:
            pct = r["Progress"]
            sc = "#30b86a" if pct >= 100 else "#36c873" if pct >= 50 else "#d4a72c"
            stat_c = {"Open":"#36c873","Closed":"#718078"}.get(r["Status"],"#718078")
            tbl_html += f'<tr style="border-bottom:1px solid #e4ebe5">'
            tbl_html += f'<td style="padding:11px 14px;font-size:13px;color:#1c2a22;font-weight:500">{r["Title"]}</td>'
            tbl_html += f'<td style="padding:11px 14px;font-size:12px;color:#718078">{r["Domain"]}</td>'
            tbl_html += f'<td style="padding:11px 14px;font-size:12px;color:#718078">{r["Level"]}</td>'
            tbl_html += f'<td style="padding:11px 14px;font-size:12px;font-family:JetBrains Mono,monospace;color:#718078">{r["Days"]}d</td>'
            tbl_html += f'<td style="padding:11px 14px;font-size:12px;font-family:JetBrains Mono,monospace;color:#36c873;font-weight:600">{r["Applicants"]}</td>'
            tbl_html += f'<td style="padding:11px 14px;font-size:12px;font-family:JetBrains Mono,monospace;color:#1c2a22">{r["Hired/Target"]}</td>'
            tbl_html += f'<td style="padding:11px 14px;min-width:140px"><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:6px;background:#e4ebe5;border-radius:3px;overflow:hidden"><div style="width:{min(pct,100)}%;height:100%;background:{sc};border-radius:3px"></div></div><span style="font-size:11px;color:{sc};font-family:JetBrains Mono,monospace;min-width:38px;font-weight:600">{pct}%</span></div></td>'
            tbl_html += f'<td style="padding:11px 14px"><span style="display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;background:rgba(48,54,61,0.3);color:{stat_c};border:1px solid rgba(48,54,61,0.8)">● {r["Status"]}</span></td>'
            tbl_html += "</tr>"
        tbl_html += "</tbody></table></div>"
        st.markdown(tbl_html, unsafe_allow_html=True)
    else:
        st.info("No jobs tracked yet. Results from the screening pipeline are automatically logged. Try generating sample data.")

    # Footer
    st.markdown(f"""
    <div style="margin-top:3rem;padding-top:16px;border-top:1px solid #e4ebe5;
                display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;
                font-size:11px;color:#98a49d;font-family:JetBrains Mono,monospace">
      <span>🎯 TalentOS · HR Intelligence Platform</span>
      <span>{provider_label()} · Pydantic v2 · SQLite · Streamlit</span>
      <span>{datetime.now().strftime("%d %b %Y, %H:%M")}</span>
    </div>""", unsafe_allow_html=True)
