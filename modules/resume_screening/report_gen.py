"""
TalentOS Report Generator.
Produces a dark-themed HTML report and JSON export
matching the TalentOS design system.
"""

import json
import logging
from datetime import datetime
from typing import List
from models.schemas import CandidateResult, ParsedJD, HireRecommendation

logger = logging.getLogger(__name__)

_DIMENSIONS = [
    ("Hard Skills",             "hard_skills_match",       "30%"),
    ("Business / Projects",     "business_project_match",  "25%"),
    ("Seniority / Level",       "seniority_level_match",   "15%"),
    ("Education / School",      "education_school_match",  "10%"),
    ("Soft Requirements",       "soft_requirements_match", "10%"),
    ("Low-Risk Signal",         "risk_signal_control",     "10%"),
]

_REC_STYLE = {
    HireRecommendation.STRONG_HIRE: ("#00e5a0", "rgba(0,229,160,0.12)", "rgba(0,229,160,0.3)"),
    HireRecommendation.HIRE:        ("#00d4ff", "rgba(0,212,255,0.12)", "rgba(0,212,255,0.3)"),
    HireRecommendation.MAYBE:       ("#f5a623", "rgba(245,166,35,0.12)", "rgba(245,166,35,0.3)"),
    HireRecommendation.NO_HIRE:     ("#ff4757", "rgba(255,71,87,0.12)", "rgba(255,71,87,0.3)"),
}


def _score_color(score: float) -> str:
    if score >= 7: return "#00e5a0"
    if score >= 5: return "#f5a623"
    return "#ff4757"


def _score_bar(score: float) -> str:
    pct   = score * 10
    color = _score_color(score)
    return (
        f'<div style="display:flex;align-items:center;gap:8px">'
        f'<div style="flex:1;height:4px;background:#1e2d3d;border-radius:2px;overflow:hidden">'
        f'<div style="width:{pct}%;height:100%;background:{color};border-radius:2px"></div>'
        f'</div>'
        f'<span style="font-family:JetBrains Mono,monospace;font-size:12px;'
        f'color:{color};width:28px;text-align:right;flex-shrink:0">{score:.1f}</span>'
        f'</div>'
    )


def _candidate_card(c: CandidateResult, rank: int) -> str:
    rec        = c.hire_recommendation
    tc, bg, bc = _REC_STYLE.get(rec, ("#8ba4bc","#0d1117","#1e2d3d"))
    score_c    = _score_color(c.weighted_total)

    override_block = ""
    if c.override_applied:
        override_block = (
            f'<div style="margin-top:12px;padding:8px 12px;background:rgba(168,85,247,0.1);'
            f'border:1px solid rgba(168,85,247,0.3);border-radius:6px;'
            f'font-family:JetBrains Mono,monospace;font-size:11px;color:#c084fc">'
            f'⚡ HR OVERRIDE · {c.override_reason}</div>'
        )

    dim_rows = ""
    for label, key, _ in _DIMENSIONS:
        dim = getattr(c.scores, key)
        weight_value = float(c.scores.dimension_weights.get(key, 0))
        weight = f"{int(round(weight_value * 100))}%"
        sc  = _score_color(dim.score)
        pct = dim.score * 10
        dim_rows += (
            f'<tr>'
            f'<td style="padding:9px 12px;font-size:12px;color:#8ba4bc;white-space:nowrap">{label}</td>'
            f'<td style="padding:9px 12px;font-family:JetBrains Mono,monospace;font-size:11px;color:#4a6278">{weight}</td>'
            f'<td style="padding:9px 12px;width:130px">'
            f'<div style="display:flex;align-items:center;gap:6px">'
            f'<div style="flex:1;height:4px;background:#1e2d3d;border-radius:2px;overflow:hidden">'
            f'<div style="width:{pct}%;height:100%;background:{sc};border-radius:2px"></div></div>'
            f'<span style="font-family:JetBrains Mono,monospace;font-size:11px;color:{sc};'
            f'width:24px;text-align:right;flex-shrink:0">{dim.score:.1f}</span>'
            f'</div></td>'
            f'<td style="padding:9px 12px;font-size:11px;color:#4a6278;line-height:1.5">{dim.justification}</td>'
            f'</tr>'
        )

    return f'''
<div style="border:1px solid #1e2d3d;border-radius:10px;margin-bottom:16px;
            overflow:hidden;background:#0d1117">
  <!-- Header -->
  <div style="padding:16px 20px;border-bottom:1px solid #1e2d3d;
              display:flex;align-items:center;justify-content:space-between;
              flex-wrap:wrap;gap:12px;background:#111820">
    <div style="display:flex;align-items:center;gap:14px">
      <div style="width:36px;height:36px;border-radius:50%;background:#141c24;
                  border:1px solid #1e2d3d;display:flex;align-items:center;
                  justify-content:center;font-family:JetBrains Mono,monospace;
                  font-size:13px;color:#f5a623;font-weight:500">#{rank}</div>
      <div>
        <div style="font-family:Syne,sans-serif;font-size:16px;font-weight:700;
                    color:#e2eaf4">{c.profile.candidate_name}</div>
        <div style="font-family:JetBrains Mono,monospace;font-size:10px;
                    color:#4a6278;margin-top:2px">{c.profile.source_file}</div>
      </div>
      {'<span style="font-family:JetBrains Mono,monospace;font-size:10px;color:#a855f7;background:rgba(168,85,247,0.1);border:1px solid rgba(168,85,247,0.3);padding:2px 8px;border-radius:3px;margin-left:8px">⚡ OVERRIDE</span>' if c.override_applied else ''}
    </div>
    <div style="display:flex;align-items:center;gap:16px">
      <div style="text-align:right">
        <div style="font-family:Syne,sans-serif;font-size:2rem;font-weight:800;
                    color:{score_c};line-height:1">{c.weighted_total:.1f}</div>
        <div style="font-family:JetBrains Mono,monospace;font-size:9px;
                    color:#4a6278;letter-spacing:0.1em">/ 10.0 WEIGHTED</div>
      </div>
      <span style="font-family:JetBrains Mono,monospace;font-size:11px;
                   color:{tc};background:{bg};border:1px solid {bc};
                   padding:4px 12px;border-radius:4px">{rec.value.upper()}</span>
    </div>
  </div>
  <!-- Meta tags -->
  <div style="padding:12px 20px;border-bottom:1px solid #1e2d3d;
              display:flex;gap:8px;flex-wrap:wrap">
    <span style="font-family:JetBrains Mono,monospace;font-size:10px;color:#f5a623;
                 background:rgba(245,166,35,0.1);border:1px solid rgba(245,166,35,0.2);
                 padding:2px 8px;border-radius:3px">{c.profile.total_experience_years} yrs exp</span>
    <span style="font-family:JetBrains Mono,monospace;font-size:10px;color:#f5a623;
                 background:rgba(245,166,35,0.1);border:1px solid rgba(245,166,35,0.2);
                 padding:2px 8px;border-radius:3px">{len(c.profile.skills)} skills listed</span>
    <span style="font-family:JetBrains Mono,monospace;font-size:10px;color:#f5a623;
                 background:rgba(245,166,35,0.1);border:1px solid rgba(245,166,35,0.2);
                 padding:2px 8px;border-radius:3px">{len(c.profile.projects)} projects</span>
  </div>
  <!-- Rubric table -->
  <div style="padding:4px 8px">
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="border-bottom:1px solid #1e2d3d">
          <th style="padding:8px 12px;text-align:left;font-family:JetBrains Mono,monospace;
                     font-size:9px;color:#4a6278;font-weight:400;letter-spacing:0.1em;
                     text-transform:uppercase">Dimension</th>
          <th style="padding:8px 12px;text-align:left;font-family:JetBrains Mono,monospace;
                     font-size:9px;color:#4a6278;font-weight:400;letter-spacing:0.1em;
                     text-transform:uppercase">Weight</th>
          <th style="padding:8px 12px;text-align:left;font-family:JetBrains Mono,monospace;
                     font-size:9px;color:#4a6278;font-weight:400;letter-spacing:0.1em;
                     text-transform:uppercase;width:140px">Score</th>
          <th style="padding:8px 12px;text-align:left;font-family:JetBrains Mono,monospace;
                     font-size:9px;color:#4a6278;font-weight:400;letter-spacing:0.1em;
                     text-transform:uppercase">Justification</th>
        </tr>
      </thead>
      <tbody>{dim_rows}</tbody>
    </table>
  </div>
  {override_block}
</div>'''


def generate_html_report(
    candidates: List[CandidateResult],
    jd: ParsedJD,
    output_path: str
) -> str:
    now          = datetime.now()
    ts_display   = now.strftime("%B %d, %Y · %H:%M")
    ts_mono      = now.strftime("%Y-%m-%d %H:%M")
    hire_count   = sum(1 for c in candidates
                       if c.hire_recommendation in
                       [HireRecommendation.STRONG_HIRE, HireRecommendation.HIRE])
    strong_count = sum(1 for c in candidates
                       if c.hire_recommendation == HireRecommendation.STRONG_HIRE)

    rec_counts = {}
    for c in candidates:
        r = c.hire_recommendation.value
        rec_counts[r] = rec_counts.get(r, 0) + 1

    summary_pills = ""
    pill_styles = {
        "Strong Hire": ("#00e5a0","rgba(0,229,160,0.12)","rgba(0,229,160,0.3)"),
        "Hire":        ("#00d4ff","rgba(0,212,255,0.12)","rgba(0,212,255,0.3)"),
        "Maybe":       ("#f5a623","rgba(245,166,35,0.12)","rgba(245,166,35,0.3)"),
        "No Hire":     ("#ff4757","rgba(255,71,87,0.12)","rgba(255,71,87,0.3)"),
    }
    for label, count in rec_counts.items():
        tc, bg, bc = pill_styles.get(label, ("#8ba4bc","#0d1117","#1e2d3d"))
        summary_pills += (
            f'<span style="font-family:JetBrains Mono,monospace;font-size:11px;'
            f'color:{tc};background:{bg};border:1px solid {bc};'
            f'padding:4px 12px;border-radius:4px;margin-right:8px">'
            f'{label.upper()}: {count}</span>'
        )

    req_skills = ", ".join(jd.required_skills[:10])
    cards_html = "".join(_candidate_card(c, c.rank) for c in candidates)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TalentOS · {jd.job_title} · Shortlist</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=JetBrains+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#080c10;--bg2:#0d1117;--bg3:#111820;--surface:#141c24;
  --border:#1e2d3d;--border2:#243447;
  --amber:#f5a623;--cyan:#00d4ff;--green:#00e5a0;--red:#ff4757;
  --text:#e2eaf4;--text2:#8ba4bc;--text3:#4a6278;
}}
body{{font-family:'DM Sans',sans-serif;background:var(--bg);color:var(--text2);
      line-height:1.6;min-height:100vh}}
.container{{max-width:980px;margin:0 auto;padding:40px 24px}}
::-webkit-scrollbar{{width:4px}}
::-webkit-scrollbar-track{{background:var(--bg)}}
::-webkit-scrollbar-thumb{{background:var(--border2);border-radius:2px}}
</style>
</head>
<body>
<div class="container">

  <!-- TOP BAR -->
  <div style="display:flex;align-items:center;justify-content:space-between;
              padding-bottom:20px;border-bottom:1px solid #1e2d3d;margin-bottom:28px">
    <div style="display:flex;align-items:center;gap:10px">
      <span style="font-family:Syne,sans-serif;font-size:1.1rem;font-weight:800;
                   color:#e2eaf4;letter-spacing:-0.02em">⬡ TalentOS</span>
      <span style="font-family:JetBrains Mono,monospace;font-size:9px;color:#4a6278;
                   letter-spacing:0.1em;text-transform:uppercase">HR Intelligence Platform</span>
    </div>
    <span style="font-family:JetBrains Mono,monospace;font-size:10px;color:#4a6278">{ts_mono}</span>
  </div>

  <!-- HERO -->
  <div style="margin-bottom:32px">
    <div style="font-family:JetBrains Mono,monospace;font-size:10px;color:#f5a623;
                letter-spacing:0.12em;text-transform:uppercase;margin-bottom:8px">
      Shortlist Report
    </div>
    <div style="font-family:Syne,sans-serif;font-size:2rem;font-weight:800;
                color:#e2eaf4;letter-spacing:-0.03em;margin-bottom:6px">
      {jd.job_title}
    </div>
    <div style="font-family:JetBrains Mono,monospace;font-size:11px;color:#4a6278;
                display:flex;gap:16px;flex-wrap:wrap">
      <span>{jd.domain}</span>
      <span>·</span>
      <span>{jd.seniority_level}</span>
      <span>·</span>
      <span>Min {jd.min_experience_years}+ yrs</span>
      <span>·</span>
      <span>Generated {ts_display}</span>
    </div>
  </div>

  <!-- STATS ROW -->
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:28px">
    {_stat_card("EVALUATED", len(candidates), "#8ba4bc")}
    {_stat_card("STRONG HIRE", strong_count, "#00e5a0")}
    {_stat_card("RECOMMENDED", hire_count, "#00d4ff")}
    {_stat_card("NO HIRE", rec_counts.get("No Hire",0), "#ff4757")}
  </div>

  <!-- BREAKDOWN -->
  <div style="background:#0d1117;border:1px solid #1e2d3d;border-radius:8px;
              padding:14px 18px;margin-bottom:20px;display:flex;align-items:center;
              gap:12px;flex-wrap:wrap">
    <span style="font-family:JetBrains Mono,monospace;font-size:9px;color:#4a6278;
                 letter-spacing:0.1em;text-transform:uppercase;flex-shrink:0">Breakdown</span>
    {summary_pills}
  </div>

  <!-- JD SKILLS -->
  <div style="background:#0d1117;border:1px solid #1e2d3d;border-radius:8px;
              padding:14px 18px;margin-bottom:28px">
    <div style="font-family:JetBrains Mono,monospace;font-size:9px;color:#4a6278;
                letter-spacing:0.1em;text-transform:uppercase;margin-bottom:8px">
      Required Skills Evaluated Against
    </div>
    <div style="font-size:12px;color:#8ba4bc">{req_skills}</div>
  </div>

  <!-- DIVIDER -->
  <div style="font-family:JetBrains Mono,monospace;font-size:9px;color:#4a6278;
              letter-spacing:0.12em;text-transform:uppercase;margin-bottom:14px">
    ◈ Ranked Shortlist
  </div>

  <!-- CANDIDATE CARDS -->
  {cards_html}

  <!-- FOOTER -->
  <div style="margin-top:40px;padding-top:20px;border-top:1px solid #1e2d3d;
              display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;
              font-family:JetBrains Mono,monospace;font-size:9px;color:#4a6278">
    <span>⬡ TALENTOS · HR INTELLIGENCE PLATFORM</span>
    <span>GROQ · LLAMA-3.3-70B · PYDANTIC V2 · SENTENCE-TRANSFORMERS</span>
    <span>{ts_display}</span>
  </div>

</div>
</body>
</html>'''

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML report written: {output_path}")
    return output_path


def _stat_card(label: str, value: int, color: str) -> str:
    return (
        f'<div style="background:#0d1117;border:1px solid #1e2d3d;border-radius:8px;'
        f'padding:16px 18px">'
        f'<div style="font-family:JetBrains Mono,monospace;font-size:9px;color:#4a6278;'
        f'letter-spacing:0.1em;text-transform:uppercase;margin-bottom:6px">{label}</div>'
        f'<div style="font-family:Syne,sans-serif;font-size:2rem;font-weight:800;'
        f'color:{color};line-height:1">{value}</div>'
        f'</div>'
    )


def generate_json_export(
    candidates: List[CandidateResult],
    jd: ParsedJD,
    output_path: str
) -> str:
    export = {
        "generated_at": datetime.now().isoformat(),
        "generator": "TalentOS HR Intelligence Platform",
        "job": jd.dict(),
        "total_candidates": len(candidates),
        "results": []
    }
    for c in candidates:
        export["results"].append({
            "rank": c.rank,
            "name": c.profile.candidate_name,
            "source": c.profile.source_file,
            "weighted_total": c.weighted_total,
            "recommendation": c.hire_recommendation.value,
            "override_applied": c.override_applied,
            "override_reason": c.override_reason,
            "hard_checks": c.scores.hard_checks,
            "matched_evidence": c.scores.matched_evidence,
            "gaps": c.scores.gaps,
            "risks": c.scores.risks,
            "suggested_action": c.scores.suggested_action,
            "algorithm_signals": c.scores.algorithm_signals,
            "matching_skill_id": c.scores.matching_skill_id,
            "matching_skill_name": c.scores.matching_skill_name,
            "dimension_weights": c.scores.dimension_weights,
            "scores": {
                dim_key: {
                    "score": getattr(c.scores, dim_key).score,
                    "weight": f"{int(round(float(c.scores.dimension_weights.get(dim_key, 0)) * 100))}%",
                    "justification": getattr(c.scores, dim_key).justification
                }
                for _, dim_key, weight in _DIMENSIONS
            }
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    logger.info(f"JSON export written: {output_path}")
    return output_path
