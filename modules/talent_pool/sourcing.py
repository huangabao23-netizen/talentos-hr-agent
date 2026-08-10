"""
Open-source talent sourcing helpers.

This module keeps the first sourcing loop deliberately conservative:
AI generates and explains the sourcing strategy, then extracts candidate leads
from public evidence pasted by the recruiter. Real search-provider integrations
can replace the evidence input later without changing the review workflow.
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from urllib import error, parse, request
from typing import Any, Dict, List, Optional

from models.schemas import TalentPoolRecord, TalentPoolStatus
from utils.db import (
    add_sourcing_candidate,
    add_talent,
    get_sourcing_candidate,
    get_sourcing_task,
    list_talents,
    list_sourcing_candidates,
    list_sourcing_tasks,
    sourcing_stats,
    update_sourcing_candidate_decision,
    update_sourcing_task_status,
    update_sourcing_task_strategy,
)
from utils.llm_client import chat_completion
from skills.matching.matching_skills import DIMENSION_KEYS, weights_for_skill
from modules.talent_pool.people_system import people_system_enabled, search_people_talents


DEFAULT_SOURCE_TYPES = (
    (["公司人才库"] if people_system_enabled() else [])
    + ["GitHub", "arXiv"]
)

SCORING_DIMENSIONS = [
    {"dimension": "方向匹配", "weight": "25%", "description": "是否和目标人才方向、业务场景一致。"},
    {"dimension": "公开成果", "weight": "25%", "description": "论文、开源、专利、技术文章、公开演讲等证据。"},
    {"dimension": "工业相关性", "weight": "20%", "description": "是否有业务落地、工程交付或复杂系统经验。"},
    {"dimension": "影响力", "weight": "15%", "description": "引用、star、会议分享、行业曝光或技术社区影响。"},
    {"dimension": "稀缺性", "weight": "10%", "description": "是否属于高端、难找、供给稀缺的人才方向。"},
    {"dimension": "信息可信度", "weight": "5%", "description": "是否有多个公开来源相互印证。"},
]

DIMENSION_DEFAULT_LABELS = {
    "hard_skills_match": "硬技能匹配",
    "business_project_match": "业务/项目经验匹配",
    "seniority_level_match": "年限与岗位级别匹配",
    "education_school_match": "教育/院校/专业匹配",
    "soft_requirements_match": "软性要求匹配",
    "risk_signal_control": "风险信号控制",
}


def _json_from_text(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        raise ValueError("empty response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if match:
            return json.loads(match.group(1).strip())
        start = min([i for i in [text.find("{"), text.find("[")] if i >= 0], default=-1)
        if start >= 0:
            return json.loads(text[start:])
        raise


def build_fallback_strategy(task: Dict[str, Any]) -> Dict[str, Any]:
    direction = task.get("talent_direction") or "目标方向"
    scene = task.get("business_scene") or "目标业务场景"
    level = task.get("target_level") or "目标级别"
    signals = task.get("focus_signals") or []
    signal_text = " ".join(signals) if signals else "论文 开源 技术博客 工业经验"
    return {
        "profile_summary": {
            "talent_direction": direction,
            "target_level": level,
            "business_scene": scene,
            "focus_signals": signals,
            "exclusion_rules": task.get("exclusion_rules", ""),
            "location_preference": task.get("location_preference", ""),
        },
        "core_keywords": [direction, scene, level],
        "expanded_keywords": [
            f"{direction} expert",
            f"{direction} {scene}",
            f"{scene} technical lead",
            signal_text,
        ],
        "source_priority": DEFAULT_SOURCE_TYPES,
        "search_queries": [
            f'"{direction}" "{scene}" "{level}"',
            f'"{direction}" "{signal_text}"',
            f'"{scene}" "技术分享" "算法"',
            f'site:github.com "{direction}" "{scene}"',
            f'site:arxiv.org "{direction}" "{scene}"',
        ],
        "scoring_dimensions": SCORING_DIMENSIONS,
        "risk_notes": [
            "当前任职状态需要人工确认。",
            "公开资料不能直接等同于求职意向。",
            "候选人入库和联系必须经 HR 人工确认。",
        ],
    }


def generate_sourcing_strategy(task: Dict[str, Any], use_llm: bool = True) -> Dict[str, Any]:
    if not use_llm:
        return build_fallback_strategy(task)

    prompt = f"""
你是高端技术人才寻访专家。请基于以下需求生成公开人才寻访策略。
只返回 JSON，不要返回 Markdown。

任务信息：
{json.dumps(task, ensure_ascii=False, indent=2)}

JSON 字段要求：
{{
  "profile_summary": {{
    "talent_direction": "...",
    "target_level": "...",
    "business_scene": "...",
    "focus_signals": ["..."],
    "exclusion_rules": "...",
    "location_preference": "..."
  }},
  "core_keywords": ["..."],
  "expanded_keywords": ["..."],
  "source_priority": ["GitHub", "arXiv"],
  "search_queries": ["..."],
  "scoring_dimensions": [
    {{"dimension": "方向匹配", "weight": "25%", "description": "..."}}
  ],
  "risk_notes": ["..."]
}}

要求：
- 搜索 query 默认围绕 GitHub、arXiv 生成；只有配置公司 People API 后才可使用公司人才库，Google Scholar 仅作为可选高级源。
- 不要建议绕过登录、验证码、权限墙。
- 强调候选人入库和联系必须人工确认。
"""
    try:
        data = _json_from_text(chat_completion(
            [
                {"role": "system", "content": "你只输出可解析 JSON。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1800,
        ))
        if isinstance(data, dict):
            data.setdefault("scoring_dimensions", SCORING_DIMENSIONS)
            data.setdefault("source_priority", DEFAULT_SOURCE_TYPES)
            data.setdefault("risk_notes", build_fallback_strategy(task)["risk_notes"])
            return data
    except Exception:
        pass
    return build_fallback_strategy(task)


def extract_candidate_leads(task: Dict[str, Any], public_material: str, use_llm: bool = True) -> List[Dict[str, Any]]:
    public_material = (public_material or "").strip()
    if not public_material:
        return []
    if not use_llm:
        return [_fallback_candidate(task, public_material)]

    prompt = f"""
你是高端技术人才寻访分析助手。请从公开资料中抽取可能匹配的人才线索。
只返回 JSON 数组，不要返回 Markdown。

寻访任务：
{json.dumps(task, ensure_ascii=False, indent=2)}

公开资料：
{public_material[:12000]}

每个候选人 JSON 字段：
{{
  "candidate_name": "姓名或待确认候选人",
  "current_org": "当前机构/公司/高校/未确认",
  "direction_tags": ["大模型", "Agent"],
  "match_score": 0-100,
  "recommendation_level": "高度匹配/可关注/信息不足",
  "recommendation_reason": "基于公开证据的推荐理由",
  "evidence_links": [
    {{"title": "证据标题", "url": "https://...", "evidence_type": "论文/GitHub/主页/博客/演讲/新闻", "summary": "证据摘要"}}
  ],
  "uncertainties": ["当前是否看机会未知"],
  "suggested_action": "加入人才库/重点关注/暂不处理"
}}

规则：
- 只能基于公开资料下结论。
- 没有证据的字段写“未确认”。
- 推荐理由必须能被 evidence_links 或公开资料文本支撑。
- 不要输出私人电话、住址、身份证等敏感信息。
"""
    try:
        data = _json_from_text(chat_completion(
            [
                {"role": "system", "content": "你只输出可解析 JSON。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2600,
        ))
        if isinstance(data, dict):
            data = data.get("candidates", [])
        if isinstance(data, list):
            return [_normalize_candidate(c) for c in data if isinstance(c, dict)]
    except Exception:
        pass
    return [_fallback_candidate(task, public_material)]


def save_candidate_leads(task_id: int, candidates: List[Dict[str, Any]]) -> List[int]:
    ids = []
    for candidate in candidates:
        ids.append(add_sourcing_candidate(task_id, _normalize_candidate(candidate)))
    if ids:
        update_sourcing_task_status(task_id, "已生成线索")
    return ids


def score_sourcing_candidate(
    candidate: Dict[str, Any],
    task: Dict[str, Any],
    matching_skill: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Score a sourcing lead with the same Skill dimensions used by resume screening.

    First version is deterministic and evidence-based. The Skill's dimension
    labels and weights come from the Markdown Skill files.
    """
    candidate = _normalize_candidate(candidate)
    weights = weights_for_skill(matching_skill)
    labels = matching_skill.get("dimension_labels") or {}
    combined_text = " ".join([
        candidate.get("candidate_name", ""),
        candidate.get("current_org", ""),
        " ".join(candidate.get("direction_tags") or []),
        candidate.get("recommendation_reason", ""),
        " ".join(_evidence_to_text(candidate.get("evidence_links") or [])),
        " ".join(candidate.get("uncertainties") or []),
        task.get("talent_direction", ""),
        task.get("business_scene", ""),
        task.get("description", ""),
    ]).lower()

    task_terms = _terms_from_text(" ".join([
        task.get("talent_direction", ""),
        task.get("business_scene", ""),
        task.get("description", ""),
        " ".join(task.get("focus_signals") or []),
    ]))
    tag_terms = _terms_from_text(" ".join(candidate.get("direction_tags") or []))
    overlap = len(set(task_terms) & set(tag_terms))

    dimension_scores = {
        "hard_skills_match": _bounded_score(5.5 + overlap * 0.8 + _contains_boost(combined_text, [
            "github", "代码", "开源", "rag", "agent", "llm", "tool", "模型", "系统", "工程",
        ])),
        "business_project_match": _bounded_score(5.0 + _contains_boost(combined_text, [
            "落地", "工程", "业务", "线上", "平台", "负责", "项目", "实践", "workflow", "企业级",
        ])),
        "seniority_level_match": _bounded_score(5.5 + _contains_boost(combined_text, [
            "专家", "负责人", "lead", "主导", "架构", "资深", "principal", "staff",
        ])),
        "education_school_match": _bounded_score(5.0 + _contains_boost(combined_text, [
            "论文", "arxiv", "dblp", "semantic scholar", "博士", "硕士", "高校", "实验室", "顶会", "科研",
        ])),
        "soft_requirements_match": _bounded_score(6.0 + _contains_boost(combined_text, [
            "分享", "演讲", "博客", "协作", "沟通", "复盘", "文档", "开源社区",
        ])),
        "risk_signal_control": _bounded_score(8.0 - min(len(candidate.get("uncertainties") or []), 5) * 0.5),
    }
    github_analysis = candidate.get("github_analysis") or {}
    if github_analysis:
        relevance = float(github_analysis.get("readme_relevance", 0))
        curation_score = float(github_analysis.get("curation_score", 0))
        relevance_adjustment = (relevance - 0.5) * 3.0
        dimension_scores["hard_skills_match"] = _bounded_score(
            dimension_scores["hard_skills_match"] + relevance_adjustment - 3.5 * curation_score
        )
        dimension_scores["business_project_match"] = _bounded_score(
            dimension_scores["business_project_match"] + relevance_adjustment - 4.0 * curation_score
        )
        dimension_scores["seniority_level_match"] = _bounded_score(
            dimension_scores["seniority_level_match"] - 1.5 * curation_score
        )
        dimension_scores["soft_requirements_match"] = _bounded_score(
            dimension_scores["soft_requirements_match"] - 1.0 * curation_score
        )
        dimension_scores["risk_signal_control"] = _bounded_score(
            dimension_scores["risk_signal_control"]
            - 2.0 * curation_score
            - (1.0 if github_analysis.get("owner_type") == "Organization" else 0.0)
        )

    weighted_total = 0.0
    dimensions = []
    for key in DIMENSION_KEYS:
        score = round(float(dimension_scores.get(key, 5.0)), 1)
        weight = float(weights.get(key, 0))
        weighted_total += score * weight
        dimensions.append({
            "dimension_key": key,
            "label": labels.get(key, DIMENSION_DEFAULT_LABELS.get(key, key)),
            "weight": weight,
            "score": score,
            "justification": _dimension_justification(key, candidate, task),
        })

    total_100 = round(weighted_total * 10, 1)
    if github_analysis and float(github_analysis.get("curation_score", 0)) >= 0.5:
        total_100 = min(total_100, 55.0)
    candidate["match_score"] = total_100
    candidate["recommendation_level"] = (
        "高度匹配" if total_100 >= 80 else "可关注" if total_100 >= 65 else "信息不足"
    )
    candidate["skill_match"] = {
        "matching_skill_id": matching_skill.get("skill_id", ""),
        "matching_skill_name": matching_skill.get("skill_name", ""),
        "hiring_type": matching_skill.get("hiring_type", ""),
        "focus_summary": matching_skill.get("focus_summary", ""),
        "total_score": total_100,
        "dimensions": dimensions,
    }
    return candidate


def score_sourcing_candidates(
    candidates: List[Dict[str, Any]],
    task: Dict[str, Any],
    matching_skill: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return [score_sourcing_candidate(candidate, task, matching_skill) for candidate in candidates]


def generate_candidates_from_talent_pool(
    task: Dict[str, Any],
    matching_skill: Dict[str, Any],
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search local talent pool and configured People system, then convert records into sourcing leads."""
    records = list_talents(limit=1000)
    query_terms = _terms_from_text(" ".join([
        task.get("talent_direction", ""),
        task.get("business_scene", ""),
        task.get("description", ""),
        " ".join(task.get("focus_signals") or []),
    ]))
    candidates = []
    for record in records:
        text = " ".join([
            record.candidate_name,
            record.domain,
            record.seniority_level,
            " ".join(record.skills),
            " ".join(record.education),
            record.work_summary,
            record.project_summary,
            " ".join(record.tags),
        ]).lower()
        hit_count = sum(1 for term in set(query_terms) if term and term.lower() in text)
        if hit_count <= 0 and task.get("talent_direction", "").lower() not in text:
            continue
        evidence = []
        if record.project_summary:
            evidence.append({
                "title": "公司人才库项目/公开证据摘要",
                "url": "",
                "evidence_type": "公司人才库",
                "summary": record.project_summary[:240],
            })
        if record.work_summary:
            evidence.append({
                "title": "公司人才库工作摘要",
                "url": "",
                "evidence_type": "公司人才库",
                "summary": record.work_summary[:240],
            })
        candidate = {
            "candidate_name": record.candidate_name,
            "current_org": record.raw_profile and "公司人才库记录" or "未确认",
            "direction_tags": list(dict.fromkeys(record.skills + [record.domain] + record.tags)),
            "recommendation_reason": record.work_summary or record.project_summary or "公司人才库中存在与寻访任务相关的历史记录。",
            "evidence_links": evidence or [{
                "title": "公司人才库记录",
                "url": "",
                "evidence_type": "公司人才库",
                "summary": f"{record.domain} · {record.seniority_level}",
            }],
            "uncertainties": ["当前状态和求职意愿需要人工确认"],
            "suggested_action": "重点关注",
            "source_type": "公司人才库",
            "source_origin_type": "内部本地人才库",
            "authenticity_status": "待核验",
            "source_talent_pool_id": record.id,
        }
        scored = score_sourcing_candidate(candidate, task, matching_skill)
        candidates.append(scored)

    if people_system_enabled():
        people_rows = search_people_talents(
            keywords=query_terms,
            department=task.get("linked_job_profile_id", ""),
            location=task.get("location_preference", ""),
            limit=limit,
        )
        for row in people_rows:
            candidates.append(score_sourcing_candidate(_people_record_to_candidate(row, task), task, matching_skill))

    candidates.sort(key=lambda item: item.get("match_score", 0), reverse=True)
    return candidates[:limit]


def generate_candidates_from_people_system(
    task: Dict[str, Any],
    matching_skill: Dict[str, Any],
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search only the configured company People API; never reads local demo data."""
    if not people_system_enabled():
        return []
    query_terms = _terms_from_text(" ".join([
        task.get("talent_direction", ""),
        task.get("business_scene", ""),
        task.get("description", ""),
        " ".join(task.get("focus_signals") or []),
    ]))
    people_rows = search_people_talents(
        keywords=query_terms,
        department=task.get("linked_job_profile_id", ""),
        location=task.get("location_preference", ""),
        limit=limit,
    )
    candidates = [
        score_sourcing_candidate(_people_record_to_candidate(row, task), task, matching_skill)
        for row in people_rows
    ]
    candidates.sort(key=lambda item: item.get("match_score", 0), reverse=True)
    return candidates[:limit]


def _people_record_to_candidate(record: Dict[str, Any], task: Dict[str, Any]) -> Dict[str, Any]:
    name = record.get("candidate_name") or record.get("name") or record.get("display_name") or "People 系统候选人"
    skills = record.get("skills") or record.get("skill_tags") or record.get("tags") or []
    if isinstance(skills, str):
        skills = [part.strip() for part in re.split(r"[,，、/]", skills) if part.strip()]
    tags = list(dict.fromkeys([*(skills or []), record.get("domain", ""), "People系统", "内部人才库"]))
    summary = record.get("work_summary") or record.get("summary") or record.get("headline") or ""
    projects = record.get("project_summary") or record.get("projects") or ""
    people_id = record.get("id") or record.get("people_id") or record.get("candidate_id") or ""
    evidence = []
    if summary:
        evidence.append({
            "title": "People 系统履历摘要",
            "url": "",
            "evidence_type": "内部人才库",
            "summary": str(summary)[:240],
        })
    if projects:
        evidence.append({
            "title": "People 系统项目摘要",
            "url": "",
            "evidence_type": "内部人才库",
            "summary": str(projects)[:240],
        })
    return {
        "candidate_name": name,
        "current_org": record.get("current_org") or record.get("company") or "People 系统记录",
        "contact_channels": _contact_channels_from_people_record(record),
        "direction_tags": [tag for tag in tags if tag],
        "recommendation_reason": summary or projects or "People 系统中存在与寻访任务相关的候选人记录。",
        "evidence_links": evidence or [{
            "title": "People 系统记录",
            "url": "",
            "evidence_type": "内部人才库",
            "summary": f"{record.get('domain', task.get('talent_direction', ''))} · {record.get('level', '')}",
        }],
        "uncertainties": ["People 系统字段映射和候选人当前意愿需要人工确认"],
        "suggested_action": "重点关注",
        "source_type": "People 系统",
        "source_origin_type": "内部 People 系统",
        "authenticity_status": "待核验",
        "source_people_id": people_id,
    }


def _contact_channels_from_people_record(record: Dict[str, Any]) -> List[Dict[str, str]]:
    channels: List[Dict[str, str]] = []
    field_map = [
        ("email", "邮箱"),
        ("work_email", "工作邮箱"),
        ("phone", "电话"),
        ("mobile", "手机号"),
        ("im", "IM"),
        ("lark", "飞书"),
        ("linkedin", "LinkedIn"),
        ("github", "GitHub"),
        ("homepage", "个人主页"),
    ]
    for field, label in field_map:
        value = str(record.get(field, "") or "").strip()
        if value:
            channels.append({
                "type": label,
                "value": value,
                "source": "People 系统授权字段",
                "confidence": "high",
            })
    contacts = record.get("contact_channels") or record.get("contacts") or []
    if isinstance(contacts, list):
        for item in contacts:
            if isinstance(item, dict):
                value = str(item.get("value") or item.get("url") or item.get("account") or "").strip()
                if not value:
                    continue
                channels.append({
                    "type": str(item.get("type") or item.get("channel") or "联系方式"),
                    "value": value,
                    "source": str(item.get("source") or "People 系统授权字段"),
                    "confidence": str(item.get("confidence") or "medium"),
                })
    return _dedupe_contacts(channels)


def generate_candidates_from_github_api(
    task: Dict[str, Any],
    matching_skill: Dict[str, Any],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search public GitHub repositories and convert owners/repos into sourcing leads."""
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "TalentOS-Sourcing",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    items = []
    seen_repos = set()
    for query in _build_api_queries(task, max_queries=4):
        params = parse.urlencode({
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": max(1, min(limit, 10)),
        })
        data = _http_get_json(f"https://api.github.com/search/repositories?{params}", headers=headers)
        for item in data.get("items", []) if isinstance(data, dict) else []:
            if (item.get("owner") or {}).get("type") == "Organization":
                continue
            repo_id = item.get("id") or item.get("full_name")
            if repo_id in seen_repos:
                continue
            items.append(item)
            seen_repos.add(repo_id)
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break

    candidates = []
    for item in items[:limit]:
        owner = item.get("owner") or {}
        topics = item.get("topics") or []
        language = item.get("language") or ""
        repo_name = item.get("full_name") or item.get("name") or "GitHub repository"
        stars = item.get("stargazers_count") or 0
        description = item.get("description") or ""
        html_url = item.get("html_url") or ""
        owner_url = owner.get("html_url") or (f"https://github.com/{owner.get('login')}" if owner.get("login") else "")
        readme_text = _fetch_github_readme(repo_name, headers)
        github_analysis = _analyze_github_readme(
            task=task,
            repo_name=repo_name,
            description=description,
            topics=topics,
            readme_text=readme_text,
            owner_type=owner.get("type", ""),
        )
        content_type = github_analysis["content_type"]
        matched_keywords = github_analysis["matched_keywords"]
        readme_summary = (
            f"README相关性={github_analysis['readme_relevance']:.0%}; "
            f"内容类型={content_type}; "
            f"整理/综述倾向={github_analysis['curation_score']:.0%}; "
            f"命中关键词={', '.join(matched_keywords[:8]) or '无'}"
        )
        candidate = {
            "candidate_name": owner.get("login") or repo_name,
            "current_org": f"GitHub · {owner.get('type', 'Owner')}",
            "contact_channels": _dedupe_contacts([{
                "type": "GitHub profile",
                "value": owner_url,
                "source": "公开资料",
                "confidence": "high",
            }] if owner_url else []),
            "direction_tags": list(dict.fromkeys([
                language,
                *topics[:8],
                "GitHub",
                "开源项目",
            ])),
            "recommendation_reason": (
                f"GitHub 仓库 {repo_name} 经 README 校验后，"
                f"项目类型为“{content_type}”，README 相关性为 "
                f"{github_analysis['readme_relevance']:.0%}，当前 stars={stars}。{description}"
            ),
            "evidence_links": [{
                "title": repo_name,
                "url": html_url,
                "evidence_type": "GitHub",
                "summary": (
                    f"{description} Stars: {stars}; language: {language}; "
                    f"topics: {', '.join(topics[:8])}; {readme_summary}"
                ),
            }],
            "uncertainties": [
                "GitHub 账号身份与真实候选人身份需要人工交叉确认",
                "开源贡献深度需要进一步查看 commits、issues、PR",
                "当前是否看机会未知",
            ],
            "github_analysis": github_analysis,
            "suggested_action": "重点关注",
            "source_type": "GitHub API",
            "source_origin_type": "外部公开 API",
            "authenticity_status": "待核验",
        }
        if not readme_text:
            candidate["uncertainties"].append("未获取到 README，项目相关性证据不足")
        if content_type == "资料整理/综述":
            candidate["uncertainties"].append("该仓库以资料整理、书单、导航或综述为主，不能等同于项目开发能力")
            candidate["suggested_action"] = "低优先级核验"
        if owner.get("type") == "Organization":
            candidate["uncertainties"].append("仓库所有者是组织账号，不应直接视为个人候选人")
        candidates.append(score_sourcing_candidate(candidate, task, matching_skill))

    candidates.sort(key=lambda item: item.get("match_score", 0), reverse=True)
    return candidates


def generate_candidates_from_arxiv_api(
    task: Dict[str, Any],
    matching_skill: Dict[str, Any],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search arXiv public API and convert authors into sourcing leads."""
    papers = []
    seen_ids = set()
    for query in _build_api_queries(task, max_queries=8):
        params = parse.urlencode({
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max(1, min(limit, 10)),
            "sortBy": "relevance",
            "sortOrder": "descending",
        })
        xml_text = _http_get_text(f"https://export.arxiv.org/api/query?{params}")
        if not xml_text:
            continue
        parsed = _parse_arxiv_entries(xml_text)
        for paper in parsed:
            paper_id = paper.get("url") or paper.get("title")
            if paper_id in seen_ids:
                continue
            papers.append(paper)
            seen_ids.add(paper_id)
            if len(papers) >= limit:
                break
        if len(papers) >= limit:
            break

    by_author: Dict[str, Dict[str, Any]] = {}
    for paper in papers:
        for name in paper.get("authors", [])[:3]:
            entry = by_author.setdefault(name, {
                "candidate_name": name,
                "current_org": "arXiv 作者 · 机构未确认",
                "contact_channels": [],
                "direction_tags": [task.get("talent_direction", ""), "论文", "arXiv"],
                "recommendation_reason": "",
                "evidence_links": [],
                "uncertainties": [
                    "作者机构、当前任职和求职意愿需要人工确认",
                    "arXiv 论文不等同于同行评审或工业落地能力",
                ],
                "suggested_action": "重点关注",
                "source_type": "arXiv API",
                "source_origin_type": "外部公开 API",
                "authenticity_status": "待核验",
            })
            entry["evidence_links"].append({
                "title": paper.get("title", "arXiv paper"),
                "url": paper.get("url", ""),
                "evidence_type": "论文",
                "summary": f"arXiv {paper.get('published', '')}; {paper.get('summary', '')[:220]}",
            })

    candidates = []
    for candidate in by_author.values():
        paper_count = len(candidate.get("evidence_links") or [])
        candidate["recommendation_reason"] = (
            f"论文库检索到 {paper_count} 篇与寻访方向相关的 arXiv 论文证据。"
            "适合作为科研/算法潜力线索，需进一步确认工业落地经历。"
        )
        candidates.append(score_sourcing_candidate(candidate, task, matching_skill))

    candidates.sort(key=lambda item: item.get("match_score", 0), reverse=True)
    return candidates[:limit]


def generate_candidates_from_google_scholar_api(
    task: Dict[str, Any],
    matching_skill: Dict[str, Any],
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search Google Scholar through configured third-party providers.

    Google Scholar has no official public API. This integration uses one of the
    configured providers: SerpAPI, SerpDog, or ScrapingBee.
    """
    providers = configured_google_scholar_provider_names()
    if not providers:
        return []

    results = []
    seen_results = set()
    provider_name = ""
    for provider in providers:
        for query in _build_api_queries(task, max_queries=8):
            data = _fetch_google_scholar_provider(provider, query, limit)
            items = _extract_google_scholar_items(data)
            for item in items:
                result_id = item.get("result_id") or item.get("link") or item.get("title")
                if result_id in seen_results:
                    continue
                item["_provider"] = provider
                results.append(item)
                seen_results.add(result_id)
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                provider_name = provider
                break
        if results:
            provider_name = provider_name or provider
            break

    by_author: Dict[str, Dict[str, Any]] = {}
    for item in results:
        title = item.get("title") or "Google Scholar result"
        link = item.get("link") or _first_resource_link(item)
        snippet = item.get("snippet") or ""
        publication = item.get("publication_info") or {}
        publication_summary = publication.get("summary", "")
        authors = publication.get("authors") or []
        cited_by = ((item.get("inline_links") or {}).get("cited_by") or {}).get("total", 0)

        author_names = [author.get("name") for author in authors if isinstance(author, dict) and author.get("name")]
        if not author_names:
            author_names = _authors_from_publication_summary(publication_summary)
        if not author_names:
            author_names = ["待确认作者"]

        for name in author_names[:3]:
            entry = by_author.setdefault(name, {
                "candidate_name": name,
                "current_org": "Google Scholar 作者 · 机构未确认",
                "contact_channels": [],
                "direction_tags": [task.get("talent_direction", ""), "论文", "Google Scholar"],
                "recommendation_reason": "",
                "evidence_links": [],
                "uncertainties": [
                    "Google Scholar 结果来自第三方 API，作者身份和机构需要人工确认",
                    "引用量和论文相关性需要结合原文复核",
                    "当前是否看机会未知",
                ],
                "suggested_action": "重点关注",
                "source_type": f"Google Scholar API · {item.get('_provider') or provider_name}",
                "source_origin_type": "外部公开 API",
                "authenticity_status": "待核验",
            })
            entry["evidence_links"].append({
                "title": title,
                "url": link,
                "evidence_type": "Google Scholar",
                "summary": f"{publication_summary}; cited_by={cited_by}; {snippet[:220]}",
            })

    candidates = []
    for candidate in by_author.values():
        evidence_count = len(candidate.get("evidence_links") or [])
        candidate["recommendation_reason"] = (
            f"Google Scholar 检索到 {evidence_count} 条与寻访方向相关的学术结果。"
            "适合作为论文型/科研型算法人才线索，需进一步确认工业落地经历。"
        )
        candidates.append(score_sourcing_candidate(candidate, task, matching_skill))

    candidates.sort(key=lambda item: item.get("match_score", 0), reverse=True)
    return candidates[:limit]


def confirm_sourcing_candidate_to_pool(candidate_id: int, hr_note: str = "") -> Optional[int]:
    candidate = get_sourcing_candidate(candidate_id)
    if not candidate:
        return None

    task = get_sourcing_task(candidate["task_id"]) or {}
    tags = list(dict.fromkeys(
        (candidate.get("direction_tags") or [])
        + [task.get("talent_direction", ""), "开源寻访"]
    ))
    tags = [t for t in tags if t]
    evidence_lines = []
    for ev in candidate.get("evidence_links") or []:
        if isinstance(ev, dict):
            title = ev.get("title") or ev.get("url") or "公开证据"
            url = ev.get("url", "")
            summary = ev.get("summary", "")
            evidence_lines.append(f"- {title}: {url} {summary}".strip())
        else:
            evidence_lines.append(f"- {ev}")

    record = TalentPoolRecord(
        candidate_name=candidate.get("candidate_name") or "待确认候选人",
        domain=task.get("talent_direction", ""),
        seniority_level=task.get("target_level", ""),
        total_experience_years=0.0,
        skills=candidate.get("direction_tags") or [],
        education=[],
        certifications=[],
        work_summary=candidate.get("recommendation_reason", ""),
        project_summary="\n".join(evidence_lines),
        location=task.get("location_preference", ""),
        open_to_remote=True,
        status=TalentPoolStatus.ACTIVE,
        tags=tags,
        raw_profile=json.dumps(candidate, ensure_ascii=False, indent=2),
    )
    talent_id = add_talent(record)
    update_sourcing_candidate_decision(candidate_id, "已入库", hr_note=hr_note, talent_pool_id=talent_id)
    return talent_id


def mark_sourcing_candidate(candidate_id: int, decision_status: str, hr_note: str = "") -> None:
    update_sourcing_candidate_decision(candidate_id, decision_status, hr_note=hr_note)


def _normalize_candidate(candidate: Dict[str, Any]) -> Dict[str, Any]:
    evidence = candidate.get("evidence_links") or []
    if isinstance(evidence, str):
        evidence = [{"title": evidence, "url": "", "evidence_type": "公开资料", "summary": ""}]
    normalized_evidence = []
    for ev in evidence:
        if isinstance(ev, dict):
            normalized_evidence.append({
                "title": ev.get("title", "公开证据"),
                "url": ev.get("url", ""),
                "evidence_type": ev.get("evidence_type", "公开资料"),
                "summary": ev.get("summary", ""),
            })
        else:
            normalized_evidence.append({
                "title": str(ev),
                "url": "",
                "evidence_type": "公开资料",
                "summary": "",
            })

    tags = candidate.get("direction_tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in re.split(r"[,，/、\n]", tags) if t.strip()]

    uncertainties = candidate.get("uncertainties") or []
    if isinstance(uncertainties, str):
        uncertainties = [uncertainties]
    contact_channels = _normalize_contact_channels(candidate.get("contact_channels") or [])

    score = float(candidate.get("match_score", 0) or 0)
    score = max(0.0, min(100.0, score))
    level = candidate.get("recommendation_level") or (
        "高度匹配" if score >= 80 else "可关注" if score >= 60 else "信息不足"
    )
    return {
        "candidate_name": candidate.get("candidate_name") or "待确认候选人",
        "current_org": candidate.get("current_org", "未确认"),
        "direction_tags": tags,
        "match_score": round(score, 1),
        "recommendation_level": level,
        "recommendation_reason": candidate.get("recommendation_reason", "公开资料中存在相关线索，需人工复核。"),
        "evidence_links": normalized_evidence,
        "uncertainties": uncertainties or ["当前是否看机会未知", "公开资料完整性待确认"],
        "suggested_action": candidate.get("suggested_action") or ("加入人才库" if score >= 80 else "重点关注"),
        "decision_status": candidate.get("decision_status", "待确认"),
        "source_type": candidate.get("source_type", "公开资料"),
        "source_origin_type": candidate.get("source_origin_type") or _infer_source_origin_type(candidate.get("source_type", "")),
        "authenticity_status": candidate.get("authenticity_status") or _infer_authenticity_status(candidate),
        "source_talent_pool_id": candidate.get("source_talent_pool_id"),
        "source_people_id": candidate.get("source_people_id"),
        "contact_channels": contact_channels,
        "github_analysis": candidate.get("github_analysis", {}),
        "skill_match": candidate.get("skill_match", {}),
    }


def _infer_source_origin_type(source_type: str) -> str:
    source_type = (source_type or "").lower()
    if "people" in source_type:
        return "内部 People 系统"
    if "公司人才库" in source_type:
        return "内部本地人才库"
    if "github" in source_type or "arxiv" in source_type or "scholar" in source_type:
        return "外部公开 API"
    return "未确认来源"


def _infer_authenticity_status(candidate: Dict[str, Any]) -> str:
    name = str(candidate.get("candidate_name", "")).lower()
    source_type = str(candidate.get("source_type", "")).lower()
    if any(marker in name for marker in ["测试", "test", "demo"]) or "测试" in source_type:
        return "测试样例"
    return "待核验"


def _normalize_contact_channels(channels: Any) -> List[Dict[str, str]]:
    if not channels:
        return []
    if isinstance(channels, dict):
        channels = [channels]
    if isinstance(channels, str):
        channels = [{"type": "联系方式", "value": channels, "source": "未确认", "confidence": "low"}]
    normalized = []
    for channel in channels if isinstance(channels, list) else []:
        if isinstance(channel, dict):
            value = str(channel.get("value") or channel.get("url") or channel.get("account") or "").strip()
            if not value:
                continue
            normalized.append({
                "type": str(channel.get("type") or channel.get("channel") or "联系方式"),
                "value": value,
                "source": str(channel.get("source") or "公开资料"),
                "confidence": str(channel.get("confidence") or "medium"),
            })
        elif str(channel).strip():
            normalized.append({
                "type": "联系方式",
                "value": str(channel).strip(),
                "source": "未确认",
                "confidence": "low",
            })
    return _dedupe_contacts(normalized)


def _dedupe_contacts(channels: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    deduped = []
    for channel in channels:
        value = str(channel.get("value", "")).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(channel)
    return deduped


def _evidence_to_text(evidence_links: List[Any]) -> List[str]:
    parts = []
    for ev in evidence_links:
        if isinstance(ev, dict):
            parts.extend([ev.get("title", ""), ev.get("evidence_type", ""), ev.get("summary", ""), ev.get("url", "")])
        else:
            parts.append(str(ev))
    return [part for part in parts if part]


def _build_api_query(task: Dict[str, Any]) -> str:
    queries = _build_api_queries(task, max_queries=1)
    return queries[0] if queries else task.get("talent_direction", "") or "machine learning"


def _build_api_queries(task: Dict[str, Any], max_queries: int = 4) -> List[str]:
    strategy = task.get("strategy_json") or {}
    keywords = []
    for key in ("core_keywords", "expanded_keywords"):
        values = strategy.get(key) or []
        if isinstance(values, list):
            keywords.extend(str(value) for value in values if value)
    keywords.extend([
        task.get("talent_direction", ""),
        task.get("business_scene", ""),
        " ".join(task.get("focus_signals") or []),
    ])
    alias_queries = _english_aliases_for_query(" ".join(keywords))
    keywords.extend(alias_queries)

    terms: List[str] = []
    seen = set()
    for keyword in keywords:
        for term in _terms_from_text(keyword):
            lowered = term.lower()
            if lowered not in seen:
                terms.append(term)
                seen.add(lowered)

    direction = task.get("talent_direction", "").strip()
    scene = task.get("business_scene", "").strip()
    queries = []
    if direction and scene:
        queries.append(f"{direction} {scene}")
    if direction:
        queries.append(direction)
    if scene:
        queries.append(scene)
    queries.extend(alias_queries)
    if terms:
        queries.append(" ".join(terms[:3]))
    if len(terms) > 3:
        queries.append(" ".join(terms[3:6]))

    cleaned = []
    seen_queries = set()
    for query in queries:
        query = " ".join(_terms_from_text(query)[:5]).strip()
        lowered = query.lower()
        if query and lowered not in seen_queries:
            cleaned.append(query)
            seen_queries.add(lowered)
    return cleaned[:max_queries] or ["machine learning"]


def _english_aliases_for_query(text: str) -> List[str]:
    alias_map = {
        "大模型": "large language model",
        "多模态": "multimodal",
        "视频": "video",
        "视频编辑": "video editing",
        "内容生成": "content generation",
        "生成": "generation",
        "推荐": "recommendation",
        "搜索": "search",
        "广告": "advertising",
        "算法": "machine learning",
        "自然语言": "natural language processing",
        "计算机视觉": "computer vision",
        "图像": "image",
        "语音": "speech",
        "强化学习": "reinforcement learning",
        "知识库": "knowledge base",
        "工程落地": "production system",
        "开源项目": "open source",
    }
    aliases = []
    for source, target in alias_map.items():
        if source in text:
            aliases.append(target)
    return aliases


def _http_get_json(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 12) -> Dict[str, Any]:
    req = request.Request(url, headers=headers or {})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8")
            return json.loads(payload)
    except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError):
        return {}


def _http_get_text(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 12) -> str:
    req = request.Request(url, headers=headers or {"User-Agent": "TalentOS-Sourcing"})
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8")
    except (error.HTTPError, error.URLError, TimeoutError, UnicodeDecodeError):
        return ""


def _fetch_github_readme(repo_name: str, headers: Dict[str, str]) -> str:
    if not repo_name or "/" not in repo_name:
        return ""
    readme_headers = dict(headers)
    readme_headers["Accept"] = "application/vnd.github.raw+json"
    safe_name = parse.quote(repo_name, safe="/")
    return _http_get_text(
        f"https://api.github.com/repos/{safe_name}/readme",
        headers=readme_headers,
        timeout=12,
    )[:12000]


def _analyze_github_readme(
    task: Dict[str, Any],
    repo_name: str,
    description: str,
    topics: List[str],
    readme_text: str,
    owner_type: str,
) -> Dict[str, Any]:
    strategy = task.get("strategy_json") or {}
    keyword_sources = [
        task.get("talent_direction", ""),
        task.get("business_scene", ""),
        " ".join(task.get("focus_signals") or []),
        " ".join(strategy.get("core_keywords") or []),
        " ".join(strategy.get("expanded_keywords") or []),
    ]
    keyword_sources.extend(_english_aliases_for_query(" ".join(keyword_sources)))
    ignored_terms = {"项目", "人才", "岗位", "开发", "工程", "相关", "经验", "要求", "方向"}
    task_keywords = []
    for source in keyword_sources:
        for term in _terms_from_text(source):
            lowered = term.lower()
            if lowered not in ignored_terms and lowered not in task_keywords:
                task_keywords.append(lowered)

    corpus = " ".join([repo_name, description, " ".join(topics), readme_text[:12000]]).lower()
    matched_keywords = [keyword for keyword in task_keywords if keyword in corpus]
    denominator = max(1, min(len(task_keywords), 8))
    readme_relevance = min(len(matched_keywords) / denominator, 1.0)

    implementation_markers = [
        "installation", "quick start", "usage", "api", "architecture", "training",
        "inference", "benchmark", "evaluation", "deploy", "docker", "requirements",
        "pip install", "source code", "demo", "模型训练", "推理", "部署", "架构",
        "安装", "使用方法", "实验结果", "性能测试",
    ]
    curation_markers = [
        "awesome-", "awesome ", "list of", "collection of", "resources", "resource list",
        "books", "book list", "papers list", "reading list", "tutorial list", "roadmap",
        "survey", "review paper", "bibliography", "学习资料", "资源汇总", "资料整理",
        "书单", "电子书", "pdf下载", "导航", "知识整理", "综述", "论文列表", "面试题",
    ]
    implementation_hits = [marker for marker in implementation_markers if marker in corpus]
    curation_hits = [marker for marker in curation_markers if marker in corpus]
    curation_score = min(len(curation_hits) / 3.0, 1.0)
    repo_lower = repo_name.lower()
    if any(marker in repo_lower for marker in ["awesome", "books", "resources", "roadmap", "papers"]):
        curation_score = max(curation_score, 0.8)

    if curation_score >= 0.5:
        content_type = "资料整理/综述"
    elif len(implementation_hits) >= 2:
        content_type = "代码实现/工程项目"
    else:
        content_type = "混合或证据不足"

    if content_type == "代码实现/工程项目":
        readme_relevance = min(readme_relevance + 0.15, 1.0)

    return {
        "readme_available": bool(readme_text.strip()),
        "readme_relevance": round(readme_relevance, 3),
        "content_type": content_type,
        "curation_score": round(curation_score, 3),
        "matched_keywords": matched_keywords[:12],
        "implementation_markers": implementation_hits[:8],
        "curation_markers": curation_hits[:8],
        "owner_type": owner_type or "Unknown",
    }


def _parse_arxiv_entries(xml_text: str) -> List[Dict[str, Any]]:
    if not xml_text:
        return []
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    papers = []
    for entry in root.findall("atom:entry", namespace):
        title = " ".join((entry.findtext("atom:title", default="", namespaces=namespace) or "").split())
        summary = " ".join((entry.findtext("atom:summary", default="", namespaces=namespace) or "").split())
        published = entry.findtext("atom:published", default="", namespaces=namespace) or ""
        url = entry.findtext("atom:id", default="", namespaces=namespace) or ""
        authors = []
        for author in entry.findall("atom:author", namespace):
            name = author.findtext("atom:name", default="", namespaces=namespace)
            if name:
                authors.append(name)
        papers.append({
            "title": title,
            "summary": summary,
            "published": published[:10],
            "url": url,
            "authors": authors,
        })
    return papers


def configured_google_scholar_provider_names() -> List[str]:
    providers = []
    preferred = os.environ.get("GOOGLE_SCHOLAR_PROVIDER", "auto").strip().lower()
    available = {
        "serpapi": bool(os.environ.get("SERPAPI_API_KEY", "").strip()),
        "serpdog": bool(os.environ.get("SERPDOG_API_KEY", "").strip()),
        "scrapingbee": bool(os.environ.get("SCRAPINGBEE_API_KEY", "").strip()),
    }
    if preferred in available:
        return [preferred] if available[preferred] else []
    for name in ["serpapi", "serpdog", "scrapingbee"]:
        if available[name]:
            providers.append(name)
    return providers


def _fetch_google_scholar_provider(provider: str, query: str, limit: int) -> Dict[str, Any]:
    if provider == "serpapi":
        params = parse.urlencode({
            "engine": "google_scholar",
            "q": query,
            "num": max(1, min(limit, 20)),
            "api_key": os.environ.get("SERPAPI_API_KEY", "").strip(),
        })
        return _http_get_json(f"https://serpapi.com/search.json?{params}")

    if provider == "serpdog":
        params = parse.urlencode({
            "api_key": os.environ.get("SERPDOG_API_KEY", "").strip(),
            "q": query,
            "num": max(1, min(limit, 20)),
        })
        return _http_get_json(f"https://api.serpdog.io/scholar?{params}")

    if provider == "scrapingbee":
        params = parse.urlencode({
            "api_key": os.environ.get("SCRAPINGBEE_API_KEY", "").strip(),
            "search": "google_scholar",
            "q": query,
            "country_code": "us",
            "language": "en",
        })
        return _http_get_json(f"https://app.scrapingbee.com/api/v1/?{params}")

    return {}


def _extract_google_scholar_items(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    for key in ["organic_results", "scholar_results", "results", "organic"]:
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if isinstance(data.get("data"), list):
        return [item for item in data["data"] if isinstance(item, dict)]
    return []


def _paper_external_url(paper: Dict[str, Any]) -> str:
    external_ids = paper.get("externalIds") or {}
    if external_ids.get("ArXiv"):
        return f"https://arxiv.org/abs/{external_ids['ArXiv']}"
    if external_ids.get("DOI"):
        return f"https://doi.org/{external_ids['DOI']}"
    return ""


def _first_resource_link(item: Dict[str, Any]) -> str:
    resources = item.get("resources") or []
    if resources and isinstance(resources[0], dict):
        return resources[0].get("link", "")
    return ""


def _authors_from_publication_summary(summary: str) -> List[str]:
    if not summary:
        return []
    first_part = summary.split("-", 1)[0]
    names = []
    for name in re.split(r",| and |，", first_part):
        cleaned = name.strip()
        if cleaned and len(cleaned) <= 80:
            names.append(cleaned)
    return names[:5]


def _terms_from_text(text: str) -> List[str]:
    text = (text or "").lower()
    raw_terms = re.split(r"[\s,，、/｜|;；:：()（）\[\]【】\n]+", text)
    terms = []
    for term in raw_terms:
        cleaned = term.strip().strip(".。")
        if len(cleaned) >= 2:
            terms.append(cleaned)
    return terms


def _contains_boost(text: str, markers: List[str]) -> float:
    return min(sum(1 for marker in markers if marker.lower() in text) * 0.45, 3.0)


def _bounded_score(score: float) -> float:
    return round(max(0.0, min(10.0, score)), 1)


def _dimension_justification(key: str, candidate: Dict[str, Any], task: Dict[str, Any]) -> str:
    direction = task.get("talent_direction", "目标方向")
    scene = task.get("business_scene", "目标业务场景")
    github_analysis = candidate.get("github_analysis") or {}
    if key == "hard_skills_match":
        if github_analysis:
            return (
                f"结合 README 与 {direction}/{scene} 的相关性 "
                f"({float(github_analysis.get('readme_relevance', 0)):.0%})评估；"
                f"内容类型为“{github_analysis.get('content_type', '未确认')}”，"
                "资料整理/综述类仓库已降权。"
            )
        return f"根据候选标签、公开证据与 {direction}/{scene} 的关键词重合度评估。"
    if key == "business_project_match":
        if github_analysis:
            return (
                "重点检查 README 中是否存在安装、使用、训练、推理、部署、架构和实验结果等"
                f"真实实现证据；当前类型为“{github_analysis.get('content_type', '未确认')}”。"
            )
        return "重点看公开资料中是否出现工程落地、业务项目、线上系统或平台建设证据。"
    if key == "seniority_level_match":
        return f"结合目标级别 {task.get('target_level', '未指定')} 与候选资料中的负责范围/专家信号评估。"
    if key == "education_school_match":
        return "看论文、科研、高校、专业背景等公开证据；缺失时不直接否决。"
    if key == "soft_requirements_match":
        return "根据技术分享、开源协作、文档表达等公开行为做辅助判断。"
    if key == "risk_signal_control":
        return "分数越高代表公开信息越完整、身份和证据越容易交叉验证。"
    return "基于当前公开证据和寻访任务要求评估。"


def _fallback_candidate(task: Dict[str, Any], public_material: str) -> Dict[str, Any]:
    urls = re.findall(r"https?://\S+", public_material)
    evidence = [
        {
            "title": f"公开链接 {idx + 1}",
            "url": url.rstrip(".,;，。"),
            "evidence_type": "公开资料",
            "summary": "待人工复核的公开链接。",
        }
        for idx, url in enumerate(urls[:5])
    ]
    if not evidence:
        evidence = [{
            "title": "公开资料摘录",
            "url": "",
            "evidence_type": "公开资料",
            "summary": public_material[:180],
        }]
    return _normalize_candidate({
        "candidate_name": "待确认候选人",
        "current_org": "未确认",
        "direction_tags": [task.get("talent_direction", "") or "目标方向"],
        "match_score": 55,
        "recommendation_level": "信息不足",
        "recommendation_reason": "已保存公开资料线索，但未能可靠抽取候选人身份，需要人工补充或重新用 LLM 解析。",
        "evidence_links": evidence,
        "uncertainties": ["候选人姓名未确认", "机构和级别未确认", "匹配度需要人工复核"],
        "suggested_action": "重点关注",
    })


__all__ = [
    "generate_sourcing_strategy",
    "extract_candidate_leads",
    "score_sourcing_candidate",
    "score_sourcing_candidates",
    "generate_candidates_from_talent_pool",
    "generate_candidates_from_people_system",
    "generate_candidates_from_github_api",
    "generate_candidates_from_arxiv_api",
    "generate_candidates_from_google_scholar_api",
    "save_candidate_leads",
    "confirm_sourcing_candidate_to_pool",
    "mark_sourcing_candidate",
    "list_sourcing_tasks",
    "list_sourcing_candidates",
    "sourcing_stats",
    "update_sourcing_task_strategy",
]
