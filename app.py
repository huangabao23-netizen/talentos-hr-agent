"""
TalentOS — HR Shortlisting Agent
Dark professional SaaS UI. Auto-writes config on startup.
"""

import os, sys, json, logging, tempfile, time
from pathlib import Path
from datetime import datetime

_cfg = Path(__file__).parent / ".streamlit" / "config.toml"
_cfg.parent.mkdir(exist_ok=True)
_cfg.write_text("""\
[theme]
base = "dark"
primaryColor = "#4f9cf9"
backgroundColor = "#0d1117"
secondaryBackgroundColor = "#161b22"
textColor = "#e2eaf4"
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

from agents.jd_parser import parse_jd
from agents.profile_parser import parse_profile
from agents.scoring_engine import score_candidate
from agents.ranker import rank_candidates, apply_override
from agents.report_gen import generate_html_report, generate_json_export
from agents.interview_gen import generate_interview_questions, get_skills_gap
from utils.file_loader import extract_text_from_file, extract_text_from_json
from utils.security import validate_file_extension
from models.schemas import CandidateResult, HireRecommendation

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
    page_title="TalentOS — HR Intelligence",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── CSS ────────────────────────────────────────────────────────────────────────
_css = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── BASE ── */
html,body,.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],.main,.main>div{
  background:#0d1117!important;color:#e2eaf4!important;
  font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif!important}
.main .block-container{padding:1.2rem 2rem 4rem!important;max-width:1200px!important}
*{font-family:Inter,-apple-system,BlinkMacSystemFont,sans-serif!important}

/* ── HIDE CHROME ── */
#MainMenu,footer,[data-testid="stToolbar"],[data-testid="stDecoration"],
[data-testid="stStatusWidget"],[data-testid="collapsedControl"],
button[kind="header"],div[data-testid="stSidebarCollapseButton"],
[data-testid="baseButton-headerNoPadding"]{display:none!important;visibility:hidden!important}
header[data-testid="stHeader"]{background:#0d1117!important;height:0!important;min-height:0!important}

/* ── SIDEBAR ── */
[data-testid="stSidebar"],[data-testid="stSidebar"]>div,
section[data-testid="stSidebar"]>div{
  background:#161b22!important;border-right:1px solid #21262d!important}
[data-testid="stSidebar"] *{color:#8b949e!important;font-size:12px!important}
[data-testid="stSidebar"] strong,[data-testid="stSidebar"] b,
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3{color:#e2eaf4!important}
[data-testid="stSidebar"] input{
  background:#0d1117!important;border:1px solid #30363d!important;
  color:#e2eaf4!important;border-radius:8px!important;font-size:12px!important}
[data-testid="stSidebar"] input:focus{border-color:#4f9cf9!important}

/* ── TEXT ── */
p,span,div,li{color:#8b949e!important;font-size:13px!important}
h1{font-size:1.4rem!important;font-weight:600!important;color:#e2eaf4!important;letter-spacing:-0.02em!important}
h2{font-size:1.05rem!important;font-weight:600!important;color:#e2eaf4!important}
h3{font-size:0.9rem!important;font-weight:500!important;color:#e2eaf4!important}
label{color:#c9d1d9!important;font-size:13px!important;font-weight:500!important}
strong,b{color:#e2eaf4!important}
code{background:#161b22!important;color:#4f9cf9!important;border:1px solid #30363d!important;
  border-radius:4px!important;padding:1px 5px!important;font-size:11px!important;
  font-family:'JetBrains Mono',monospace!important}

/* ── INPUTS ── */
.stTextInput>div>div,.stTextInput>div>div>input,
.stTextArea>div>div,.stTextArea>div>div>textarea{
  background:#161b22!important;border:1px solid #30363d!important;
  border-radius:8px!important;color:#e2eaf4!important;font-size:13px!important}
.stTextInput>div>div>input:focus,.stTextArea>div>div>textarea:focus{
  border-color:#4f9cf9!important;box-shadow:0 0 0 3px rgba(79,156,249,0.1)!important}
.stTextInput>div>div>input::placeholder,.stTextArea>div>div>textarea::placeholder{
  color:#484f58!important}

/* ── FILE UPLOADER ── */
[data-testid="stFileUploader"]{
    background:#161b22!important;
    border-radius:10px!important;
}

[data-testid="stFileUploaderDropzone"]{
    border:1.5px dashed #30363d!important;
    border-radius:10px!important;
    background:#161b22!important;
    padding:18px!important;
    display:flex!important;
    align-items:center!important;
    gap:12px!important;
}

[data-testid="stFileUploaderDropzone"]:hover{
    border-color:#4f9cf9!important;
}

/* FIX uploadUpload */
[data-testid="stFileUploader"] section button p{
    display:none!important;
}

[data-testid="stFileUploader"] section button::after{
    content:"Upload";
    color:#c9d1d9!important;
    font-size:13px!important;
    font-weight:500!important;
}

[data-testid="stFileUploader"] button{
    background:#0d1117!important;
    border:1px solid #30363d!important;
    border-radius:8px!important;
    padding:8px 16px!important;
    min-height:40px!important;
}

[data-testid="stFileUploader"] small{
    color:#8b949e!important;
    font-size:12px!important;
}


/* ───────── REAL uploadUpload FIX ───────── */

[data-testid="stFileUploader"] button{
    font-size:0 !important;
    color:transparent !important;
}

/* hide ALL internal upload text */
[data-testid="stFileUploader"] button *{
    display:none !important;
}

/* create clean single Upload text */
[data-testid="stFileUploader"] button::after{
    content:"Upload";
    font-size:14px !important;
    color:#e6edf3 !important;
    font-weight:500 !important;
    display:block !important;
    line-height:1 !important;
}

/* button style */
[data-testid="stFileUploader"] button{
    background:#0d1117 !important;
    border:1px solid #30363d !important;
    border-radius:8px !important;
    min-height:42px !important;
    padding:8px 18px !important;
}

/* uploader box */
[data-testid="stFileUploaderDropzone"]{
    display:flex !important;
    align-items:center !important;
    gap:14px !important;
}


/* ── BUTTONS ── */
.stButton>button{
  background:#161b22!important;border:1px solid #30363d!important;
  border-radius:8px!important;color:#c9d1d9!important;font-size:13px!important;
  font-weight:500!important;padding:0.45rem 1.2rem!important;box-shadow:none!important;
  transition:all 0.15s!important}
.stButton>button:hover{
  background:#21262d!important;border-color:#8b949e!important;color:#e2eaf4!important}
.stButton>button[kind="primary"]{
  background:#4f9cf9!important;border-color:#4f9cf9!important;color:#0d1117!important;font-weight:600!important}
.stButton>button[kind="primary"]:hover{background:#3d8ef8!important;color:#0d1117!important}

/* ── METRICS ── */
[data-testid="metric-container"],[data-testid="stMetric"]{
  background:#161b22!important;border:1px solid #21262d!important;
  border-radius:12px!important;padding:1rem 1.2rem!important}
[data-testid="stMetricLabel"] p,[data-testid="stMetricLabel"] div{
  color:#484f58!important;font-size:11px!important;text-transform:uppercase!important;
  letter-spacing:0.04em!important;font-weight:500!important}
[data-testid="stMetricValue"] div{color:#e2eaf4!important;font-size:1.8rem!important;font-weight:600!important}

/* ── EXPANDER ── */
[data-testid="stExpander"]{
    background:#161b22!important;
    border:1px solid #21262d!important;
    border-radius:12px!important;
    margin-bottom:10px!important;
    overflow:hidden!important;
}

[data-testid="stExpander"] summary{
    padding:14px 18px 14px 42px!important;
    font-size:13px!important;
    color:#e2eaf4!important;
    background:#161b22!important;
    cursor:pointer!important;
    list-style:none!important;
}

/* FIX arrow overlap */
[data-testid="stExpander"] summary::-webkit-details-marker{
    display:none!important;
}

[data-testid="stExpander"] summary::before{
    content:"▶";
    position:absolute!important;
    left:16px!important;
    top:14px!important;
    color:#8b949e!important;
    font-size:11px!important;
}

[data-testid="stExpander"][open] summary::before{
    content:"▼";
}

[data-testid="stExpander"] > details > div{
    padding:14px 18px!important;
    background:#0d1117!important;
}

/* ── ALERTS ── */
[data-testid="stAlert"]{border-radius:8px!important;font-size:13px!important;border-left-width:3px!important}
.stSuccess{background:rgba(35,134,54,0.1)!important;border-color:#238636!important}
.stSuccess *{color:#3fb950!important}
.stInfo{background:rgba(31,111,235,0.1)!important;border-color:#1f6feb!important}
.stInfo *{color:#58a6ff!important}
.stWarning{background:rgba(210,153,34,0.1)!important;border-color:#d29922!important}
.stWarning *{color:#e3b341!important}
.stError{background:rgba(218,54,51,0.1)!important;border-color:#da3633!important}
.stError *{color:#f85149!important}

/* ── PROGRESS ── */
.stProgress>div>div{background:#21262d!important;border-radius:3px!important;height:4px!important}
.stProgress>div>div>div{background:#4f9cf9!important;border-radius:3px!important}

/* ── SELECT ── */
[data-testid="stSelectbox"]>div>div{
  background:#161b22!important;border:1px solid #30363d!important;
  border-radius:8px!important;color:#e2eaf4!important}
[data-testid="stSelectbox"] *{color:#e2eaf4!important;background:#161b22!important}

/* ── MULTISELECT ── */
[data-testid="stMultiSelect"]>div{
  background:#161b22!important;border:1px solid #30363d!important;border-radius:8px!important}
[data-testid="stMultiSelect"] span[data-baseweb="tag"]{
  background:rgba(79,156,249,0.12)!important;color:#4f9cf9!important;
  border:1px solid rgba(79,156,249,0.3)!important;border-radius:20px!important;font-size:11px!important}

/* ── RADIO ── */
[data-testid="stRadio"]>div{gap:8px!important;background:transparent!important}
[data-testid="stRadio"] label{color:#c9d1d9!important;font-size:13px!important}

/* ── SLIDER ── */
[data-testid="stSlider"]>div>div{background:#30363d!important}
[data-testid="stSlider"] [role="slider"]{background:#4f9cf9!important;border-color:#4f9cf9!important}

/* ── DOWNLOAD BUTTON ── */
[data-testid="stDownloadButton"]>button{
  background:rgba(35,134,54,0.1)!important;border:1px solid #238636!important;
  color:#3fb950!important;font-weight:500!important;border-radius:8px!important;font-size:13px!important}
[data-testid="stDownloadButton"]>button:hover{background:rgba(35,134,54,0.2)!important}

/* ── PLOTLY ── */
[data-testid="stPlotlyChart"]{
  background:#161b22!important;border:1px solid #21262d!important;
  border-radius:12px!important;overflow:hidden!important}

/* ── DIVIDER ── */
hr{border:none!important;border-top:1px solid #21262d!important;margin:1rem 0!important}
[data-testid="column"]{padding:0 6px!important}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:4px;height:4px}
::-webkit-scrollbar-track{background:#0d1117}
::-webkit-scrollbar-thumb{background:#30363d;border-radius:2px}
::-webkit-scrollbar-thumb:hover{background:#8b949e}
"""
st.markdown(f"<style>{_css}</style>", unsafe_allow_html=True)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def section_label(text):
    st.markdown(
        f'<div style="font-size:10px;font-weight:500;color:#484f58;'
        f'text-transform:uppercase;letter-spacing:0.08em;'
        f'margin-bottom:8px;margin-top:4px;font-family:JetBrains Mono,monospace">{text}</div>',
        unsafe_allow_html=True)

def badge_html(text, color="gray"):
    C = {
        "green":  ("rgba(35,134,54,0.15)","#3fb950","rgba(35,134,54,0.4)"),
        "blue":   ("rgba(31,111,235,0.15)","#58a6ff","rgba(31,111,235,0.4)"),
        "amber":  ("rgba(79,156,249,0.12)","#4f9cf9","rgba(79,156,249,0.4)"),
        "red":    ("rgba(218,54,51,0.15)","#f85149","rgba(218,54,51,0.4)"),
        "purple": ("rgba(163,113,247,0.15)","#a371f7","rgba(163,113,247,0.4)"),
        "gray":   ("#21262d","#8b949e","#30363d"),
    }
    bg,tc,bc = C.get(color, C["gray"])
    return (f'<span style="display:inline-flex;align-items:center;padding:2px 10px;'
            f'border-radius:20px;font-size:11px;font-weight:500;background:{bg};'
            f'color:{tc};border:1px solid {bc};margin:2px">{text}</span>')

def score_color(s):
    return "#3fb950" if s>=7 else "#e3b341" if s>=5 else "#f85149"

def score_bar_color(s):
    return "#238636" if s>=7 else "#9e6a03" if s>=5 else "#da3633"

def dim_row_html(label, weight, score, justification):
    pct = score * 10
    sc  = score_color(score)
    bc  = score_bar_color(score)
    return f"""
    <div style="display:grid;grid-template-columns:155px 32px 100px 34px 1fr;
                gap:8px;align-items:center;padding:7px 0;
                border-bottom:1px solid #21262d">
      <span style="font-size:12px;color:#c9d1d9">{label}</span>
      <span style="font-size:11px;color:#484f58;text-align:center;
                   font-family:JetBrains Mono,monospace">{weight}</span>
      <div style="height:4px;background:#21262d;border-radius:2px;overflow:hidden">
        <div style="width:{pct}%;height:100%;background:{bc};border-radius:2px"></div>
      </div>
      <span style="font-size:12px;font-weight:600;color:{sc};text-align:right">{score:.1f}</span>
      <span style="font-size:11px;color:#484f58;line-height:1.4">{justification}</span>
    </div>"""

def iq_block_html(label, question, accent="#58a6ff", label_color="#58a6ff"):
    return f"""
    <div style="background:#161b22;border:1px solid #21262d;
                border-left:3px solid {accent};border-radius:0 8px 8px 0;
                padding:10px 14px;margin:5px 0">
      <div style="font-size:10px;font-weight:500;color:{label_color};
                  text-transform:uppercase;letter-spacing:0.06em;
                  margin-bottom:4px;font-family:JetBrains Mono,monospace">{label}</div>
      <div style="font-size:12px;color:#c9d1d9;line-height:1.5">{question}</div>
    </div>"""

def step_header(num, title):
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:10px;margin:20px 0 14px">
      <div style="width:24px;height:24px;background:#4f9cf9;border-radius:50%;
                  display:flex;align-items:center;justify-content:center;
                  font-size:11px;font-weight:700;color:#0d1117;flex-shrink:0">{num}</div>
      <div style="font-size:15px;font-weight:600;color:#e2eaf4">{title}</div>
    </div>""", unsafe_allow_html=True)

# ── CONSTANTS ──────────────────────────────────────────────────────────────────
DIMENSION_LABELS = {
    "skills_match":          ("Skills match",         "30%"),
    "experience_relevance":  ("Experience relevance", "25%"),
    "education_certs":       ("Education & certs",    "15%"),
    "project_portfolio":     ("Project / portfolio",  "20%"),
    "communication_quality": ("Communication",        "10%"),
}
DIM_SHORT   = ["Skills","Experience","Education","Portfolio","Comms"]
BADGE_COLOR = {"Strong Hire":"green","Hire":"blue","Maybe":"amber","No Hire":"red"}

# ── SESSION STATE ──────────────────────────────────────────────────────────────
for k in ["parsed_jd","ranked","run_complete"]:
    if k not in st.session_state: st.session_state[k] = None
if "interview_cache" not in st.session_state: st.session_state.interview_cache = {}
if "sample_resumes"  not in st.session_state: st.session_state.sample_resumes  = []
if "sample_jd_text"  not in st.session_state: st.session_state.sample_jd_text  = ""

# ── SIDEBAR ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:2px 0 16px">
      <div style="display:flex;align-items:center;gap:10px">
        <div style="width:32px;height:32px;background:rgba(79,156,249,0.12);border-radius:8px;
                    border:1px solid rgba(79,156,249,0.3);
                    display:flex;align-items:center;justify-content:center;font-size:16px">🎯</div>
        <div>
          <div style="font-size:15px;font-weight:600;color:#e2eaf4">TalentOS</div>
          <div style="font-size:11px;color:#484f58">HR Intelligence</div>
        </div>
      </div>
    </div>""", unsafe_allow_html=True)

    st.divider()
    groq_key = st.text_input("Groq API key", type="password",
        value=os.environ.get("GROQ_API_KEY",""), placeholder="gsk_...",
        help="Free at console.groq.com")
    if groq_key: os.environ["GROQ_API_KEY"] = groq_key

    ls_key = st.text_input("LangSmith key", type="password",
        value=os.environ.get("LANGCHAIN_API_KEY",""), placeholder="Optional — tracing")
    if ls_key:
        os.environ["LANGCHAIN_API_KEY"] = ls_key
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = "talentos-hr-agent"
        st.success("LangSmith tracing enabled")

    st.divider()
    st.markdown("""
    <div style="font-size:10px;font-weight:500;color:#484f58;
                text-transform:uppercase;letter-spacing:0.08em;
                margin-bottom:10px;font-family:JetBrains Mono,monospace">System</div>
    <div style="display:flex;flex-direction:column;gap:7px">
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#8b949e">
        <div style="width:6px;height:6px;border-radius:50%;background:#3fb950;flex-shrink:0"></div>Llama 3.3 70B · Groq</div>
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#8b949e">
        <div style="width:6px;height:6px;border-radius:50%;background:#3fb950;flex-shrink:0"></div>MiniLM-L6 embeddings</div>
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#8b949e">
        <div style="width:6px;height:6px;border-radius:50%;background:#3fb950;flex-shrink:0"></div>Pydantic v2 validation</div>
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#8b949e">
        <div style="width:6px;height:6px;border-radius:50%;background:#3fb950;flex-shrink:0"></div>Bias detection active</div>
      <div style="display:flex;align-items:center;gap:7px;font-size:12px;color:#8b949e">
        <div style="width:6px;height:6px;border-radius:50%;background:#3fb950;flex-shrink:0"></div>PII masking on</div>
    </div>""", unsafe_allow_html=True)

# ── PAGE HEADER ────────────────────────────────────────────────────────────────
st.markdown("""
<div style="padding-bottom:16px;border-bottom:1px solid #21262d;margin-bottom:4px;
            display:flex;align-items:flex-start;justify-content:space-between;flex-wrap:wrap;gap:8px">
  <div>
    <div style="font-size:1.4rem;font-weight:600;color:#e2eaf4;letter-spacing:-0.02em">
      Candidate Evaluation
    </div>
    <div style="font-size:13px;color:#8b949e;margin-top:4px">
      Upload a JD and resumes to get a ranked shortlist with AI-powered scoring
    </div>
  </div>
  <span style="display:inline-flex;align-items:center;gap:5px;padding:4px 12px;
               border-radius:20px;font-size:11px;font-weight:500;
               background:rgba(79,156,249,0.12);color:#4f9cf9;
               border:1px solid rgba(79,156,249,0.3);margin-top:4px">
    ✦ AI powered · Groq
  </span>
</div>""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 1
# ═══════════════════════════════════════════════════════════════════════════════
step_header("1","Inputs")
col1, col2 = st.columns(2, gap="medium")

with col1:
    st.markdown('<div style="font-size:13px;font-weight:500;color:#e2eaf4;margin-bottom:10px">Job description</div>', unsafe_allow_html=True)
    jd_mode = st.radio("", ["Upload file","Paste text"], horizontal=True,
                        key="jd_mode", label_visibility="collapsed")
    jd_text = ""
    if jd_mode == "Upload file":
        jd_file = st.file_uploader(
            "",
            type=["pdf","docx","txt"],
            key="jd_file",
            label_visibility="collapsed"
        )
        if jd_file:
            jd_text = extract_text_from_file(jd_file.read(), jd_file.name)
            if jd_text: st.success(f"✓ {jd_file.name} — {len(jd_text):,} characters")
            else: st.error("Could not extract text.")
    else:
        jd_text = st.text_area("", height=160,
            placeholder="Paste full job description here...",
            key="jd_paste", label_visibility="collapsed")

    if st.button("Load sample JD", use_container_width=True, key="load_jd"):
        p = Path(__file__).parent / "sample_data" / "jd_sample.txt"
        if p.exists():
            st.session_state.sample_jd_text = p.read_text(encoding="utf-8")
            st.success("Sample JD loaded — Senior Machine Learning Engineer")

    if st.session_state.sample_jd_text and not jd_text:
        jd_text = st.session_state.sample_jd_text

    if jd_text.strip():
        biased = check_jd_bias(jd_text)
        if biased:
            pills = "".join([f'<span style="display:inline-block;background:rgba(163,113,247,0.15);color:#a371f7;border:1px solid rgba(163,113,247,0.3);border-radius:4px;padding:1px 8px;font-size:11px;margin:2px">{t}</span>' for t in biased])
            st.markdown(f'<div style="margin-top:8px;padding:8px 12px;background:rgba(163,113,247,0.1);border:1px solid rgba(163,113,247,0.3);border-radius:8px;font-size:12px;color:#a371f7">⚠ Biased language: {pills}</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div style="font-size:13px;font-weight:500;color:#e2eaf4;margin-bottom:10px">Candidate profiles</div>', unsafe_allow_html=True)
    resume_files = st.file_uploader(
        "",
        type=["pdf","docx","txt"],
        accept_multiple_files=True,
        key="resumes",
        label_visibility="collapsed"
    )
    linkedin_files = st.file_uploader(
        "",
        type=["json"],
        accept_multiple_files=True,
        key="linkedin",
        label_visibility="collapsed"
    )
    if st.button("Load 5 sample resumes", use_container_width=True, key="load_res"):
        d = Path(__file__).parent / "sample_data" / "resumes"
        if d.exists():
            files = list(d.glob("*.txt"))
            st.session_state.sample_resumes = [(f.name,f.read_bytes()) for f in sorted(files)]
            st.success(f"✓ {len(files)} sample resumes loaded")
    total = len(resume_files)+len(linkedin_files)+len(st.session_state.sample_resumes)
    if total: st.info(f"✓ {total} candidate file(s) queued and ready")

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 2
# ═══════════════════════════════════════════════════════════════════════════════
step_header("2","Run agent")
st.markdown("""
<div style="background:#161b22;border:1px solid #21262d;border-radius:12px;padding:16px;margin-bottom:8px">
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px">
    <div style="background:#0d1117;border-radius:8px;padding:10px;border:1px solid #21262d">
      <div style="font-size:10px;color:#484f58;margin-bottom:2px;font-family:JetBrains Mono,monospace">LLM</div>
      <div style="font-size:13px;font-weight:500;color:#e2eaf4">Llama 3.3 70B</div>
    </div>
    <div style="background:#0d1117;border-radius:8px;padding:10px;border:1px solid #21262d">
      <div style="font-size:10px;color:#484f58;margin-bottom:2px;font-family:JetBrains Mono,monospace">Embeddings</div>
      <div style="font-size:13px;font-weight:500;color:#e2eaf4">MiniLM-L6-v2</div>
    </div>
    <div style="background:#0d1117;border-radius:8px;padding:10px;border:1px solid #21262d">
      <div style="font-size:10px;color:#484f58;margin-bottom:2px;font-family:JetBrains Mono,monospace">Validation</div>
      <div style="font-size:13px;font-weight:500;color:#e2eaf4">Pydantic v2</div>
    </div>
  </div>
""", unsafe_allow_html=True)
run_clicked = st.button("▶  Run shortlisting pipeline", type="primary",
                         use_container_width=True, key="run_btn")

if run_clicked:
    if not os.environ.get("GROQ_API_KEY"):
        st.error("Groq API key required — enter it in the sidebar."); st.stop()
    if not jd_text.strip():
        st.error("Please provide a job description."); st.stop()

    all_profiles = [(f.name, f.read()) for f in resume_files]
    for f in linkedin_files:
        try:
            data = json.loads(f.read().decode("utf-8"))
            txt  = extract_text_from_json(data)
            if txt: all_profiles.append((f.name, txt.encode()))
        except Exception as e: st.warning(f"LinkedIn JSON error: {f.name} — {e}")
    for name,content in st.session_state.sample_resumes:
        all_profiles.append((name, content))

    if not all_profiles: st.error("Please upload at least one resume."); st.stop()

    prog   = st.progress(0, text="Starting pipeline...")
    status = st.empty()
    errors = []

    status.info("Parsing job description...")
    try:
        parsed_jd = parse_jd(jd_text)
        st.session_state.parsed_jd = parsed_jd
        status.success(f"Job description parsed — {parsed_jd.job_title} · {parsed_jd.seniority_level}")
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

    if not candidates: st.error("No profiles could be parsed."); st.stop()

    results = []
    for i,profile in enumerate(candidates):
        status.info(f"Scoring {i+1} of {len(candidates)} — {profile.candidate_name}")
        try:
            scores = score_candidate(parsed_jd, profile)
            results.append(CandidateResult(profile=profile, scores=scores))
            prog.progress(50+int(40*(i+1)/len(candidates)))
        except Exception as e:
            errors.append(f"Scoring error — {profile.candidate_name}: {e}")

    if not results: st.error("Scoring failed for all candidates."); st.stop()

    ranked = rank_candidates(results)
    st.session_state.ranked       = ranked
    st.session_state.run_complete = True
    st.session_state.interview_cache = {}
    prog.progress(100)
    status.success(f"Complete — {len(ranked)} candidates evaluated and ranked")

    if errors:
        with st.expander(f"{len(errors)} warning(s)"):
            for e in errors: st.warning(e)

# ═══════════════════════════════════════════════════════════════════════════════
# STEP 3
# ═══════════════════════════════════════════════════════════════════════════════
if st.session_state.run_complete and st.session_state.ranked:
    ranked = st.session_state.ranked
    jd     = st.session_state.parsed_jd

    step_header("3","Results")

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

    # Radar
    section_label("Candidate comparison — radar chart")
    st.caption("Select two or more candidates to compare across all five scoring dimensions.")
    names = [f"#{c.rank} {c.profile.candidate_name}" for c in ranked]
    sel   = st.multiselect("", names, default=names[:min(3,len(names))],
                            key="radar", label_visibility="collapsed")
    if len(sel) >= 2:
        COLORS = ["#4f9cf9","#58a6ff","#3fb950","#f85149","#a371f7"]
        fig = go.Figure()
        for i,c in enumerate([x for x in ranked if f"#{x.rank} {x.profile.candidate_name}" in sel]):
            vals = [c.scores.skills_match.score, c.scores.experience_relevance.score,
                    c.scores.education_certs.score, c.scores.project_portfolio.score,
                    c.scores.communication_quality.score]
            fig.add_trace(go.Scatterpolar(
                r=vals+[vals[0]], theta=DIM_SHORT+[DIM_SHORT[0]],
                fill="toself",
                name=f"#{c.rank} {c.profile.candidate_name} ({c.weighted_total:.1f}/10)",
                line_color=COLORS[i%len(COLORS)], opacity=0.75, line=dict(width=2)
            ))
        fig.update_layout(
            polar=dict(
                bgcolor="#161b22",
                radialaxis=dict(visible=True, range=[0,10],
                    tickfont=dict(size=9,color="#484f58",family="Inter"),
                    gridcolor="#21262d", linecolor="#30363d"),
                angularaxis=dict(gridcolor="#21262d", linecolor="#30363d",
                    tickfont=dict(size=11,color="#8b949e",family="Inter"))
            ),
            paper_bgcolor="#161b22", plot_bgcolor="#161b22",
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=-0.25,
                font=dict(size=11,color="#8b949e",family="Inter"),
                bgcolor="#161b22", bordercolor="#21262d", borderwidth=1),
            height=400, margin=dict(t=20,b=90,l=40,r=40)
        )
        st.plotly_chart(fig, use_container_width=True)
    elif len(sel)==1:
        st.info("Select at least two candidates to compare.")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    section_label(f"Ranked shortlist — {jd.job_title}")

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
                st.markdown(f'<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:12px">{tags}</div>', unsafe_allow_html=True)

                section_label("Skills gap analysis")
                if gap:
                    pills = "".join([f'<span style="display:inline-block;background:rgba(218,54,51,0.1);color:#f85149;border:1px solid rgba(218,54,51,0.3);border-radius:20px;padding:2px 8px;font-size:11px;margin:2px">✕ {s}</span>' for s in gap[:10]])
                    st.markdown(pills, unsafe_allow_html=True)
                else:
                    st.markdown('<span style="display:inline-block;background:rgba(35,134,54,0.1);color:#3fb950;border:1px solid rgba(35,134,54,0.3);border-radius:20px;padding:2px 10px;font-size:11px">✓ All required skills present</span>', unsafe_allow_html=True)

                st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
                section_label("Scoring rubric")
                rows_html = '<div style="border-top:1px solid #21262d">'
                for dim_key,(dim_label,weight) in DIMENSION_LABELS.items():
                    dim = getattr(candidate.scores, dim_key)
                    rows_html += dim_row_html(dim_label, weight, dim.score, dim.justification)
                rows_html += '</div>'
                st.markdown(rows_html, unsafe_allow_html=True)

                if candidate.override_applied:
                    st.markdown(f'<div style="margin-top:10px;padding:8px 12px;background:rgba(163,113,247,0.1);border:1px solid rgba(163,113,247,0.3);border-radius:8px;font-size:12px;color:#a371f7">Override: {candidate.override_reason}</div>', unsafe_allow_html=True)

                st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
                section_label("Tailored interview questions")
                ck = f"iq_{candidate.profile.candidate_name}"
                if ck in st.session_state.interview_cache:
                    iq = st.session_state.interview_cache[ck]
                    iq_html = ""
                    for i,q in enumerate(iq.get("technical_questions",[]),1):
                        iq_html += iq_block_html(f"Technical question {i}", q,"#58a6ff","#58a6ff")
                    for i,q in enumerate(iq.get("gap_questions",[]),1):
                        iq_html += iq_block_html(f"Gap probe {i}", q,"#4f9cf9","#4f9cf9")
                    cq = iq.get("culture_question","")
                    if cq: iq_html += iq_block_html("Behavioural question", cq,"#3fb950","#3fb950")
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
                <div style="background:#0d1117;border:1px solid #21262d;border-radius:12px;
                            padding:16px;text-align:center;margin-bottom:12px">
                  <div style="font-size:2.4rem;font-weight:600;color:{sc_col};line-height:1">
                    {candidate.weighted_total:.1f}
                  </div>
                  <div style="font-size:11px;color:#484f58;margin-top:4px;
                               font-family:JetBrains Mono,monospace">out of 10.0</div>
                  <div style="margin-top:10px">{badge_html(rec_val,bc)}</div>
                </div>""", unsafe_allow_html=True)

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

    # ═══════════════════════════════════════════════════════════════════════════
    # STEP 4
    # ═══════════════════════════════════════════════════════════════════════════
    step_header("4","Export")
    st.markdown('<div style="font-size:13px;color:#8b949e;margin-bottom:14px">Download your shortlist. HTML reports open in any browser and can be shared with hiring managers.</div>', unsafe_allow_html=True)

    ts   = datetime.now().strftime("%Y%m%d_%H%M")
    slug = jd.job_title.replace(" ","_")
    c1,c2,c3 = st.columns(3, gap="medium")

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
            rows = [{
                "Rank": c.rank,"Name": c.profile.candidate_name,
                "Source": c.profile.source_file,
                "Experience (yrs)": c.profile.total_experience_years,
                "Skills listed": len(c.profile.skills),
                "Weighted total": round(c.weighted_total,2),
                "Recommendation": c.hire_recommendation.value,
                "Skills match": c.scores.skills_match.score,
                "Experience relevance": c.scores.experience_relevance.score,
                "Education & certs": c.scores.education_certs.score,
                "Portfolio": c.scores.project_portfolio.score,
                "Communication": c.scores.communication_quality.score,
                "Skills gap": ", ".join(get_skills_gap(jd,c.profile)),
                "Override note": c.override_reason or "",
            } for c in ranked]
            csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
            st.download_button("↓ Download CSV", data=csv,
                file_name=f"talentos_{slug}_{ts}.csv",
                mime="text/csv", use_container_width=True)

    st.markdown(f"""
    <div style="margin-top:3rem;padding-top:16px;border-top:1px solid #21262d;
                display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;
                font-size:11px;color:#484f58;font-family:JetBrains Mono,monospace">
      <span>TalentOS · HR Intelligence Platform</span>
      <span>Groq · Llama 3.3 70B · Pydantic v2 · Sentence-Transformers</span>
      <span>{datetime.now().strftime("%d %b %Y, %H:%M")}</span>
    </div>""", unsafe_allow_html=True)
