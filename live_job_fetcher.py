"""
Live Job Feed Fetcher & Aggregator for Resume AI.
Pulls real, active job postings from public developer job feeds (Remotive, Arbeitnow)
and extracts structured skill requirements using spaCy NLP.
"""

import os
import re
import json
import html
import urllib.request
import logging
from typing import List, Dict, Any

from skills_data import normalize_skill
from resume_parser import get_spacy_nlp, extract_skills_nlp

logger = logging.getLogger(__name__)

# Zero hardcoded mock jobs - all postings are fetched dynamically from live APIs



def _clean_html(raw_html: str) -> str:
    """Removes HTML tags and unescapes entities."""
    if not raw_html:
        return ""
    text = re.sub(r"<[^<]+?>", " ", raw_html)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:1500]


def _infer_seniority(title: str) -> tuple[str, float]:
    """Infers seniority level and minimum years of experience from job title."""
    t = title.lower()
    if any(k in t for k in ["staff", "lead", "principal", "head", "architect", "director"]):
        return "Lead", 5.0
    if any(k in t for k in ["senior", "sr.", "sr ", "iii", "expert"]):
        return "Senior", 3.0
    if any(k in t for k in ["junior", "jr.", "jr ", "entry", "intern", "associate"]):
        return "Entry-Level", 0.5
    return "Mid-Level", 2.0


def fetch_live_remote_jobs(limit: int = 40) -> List[Dict[str, Any]]:
    """
    Fetches real-time, live jobs from public developer feeds (Remotive & Arbeitnow).
    Uses spaCy NLP to extract verified canonical technical skills.
    """
    nlp = get_spacy_nlp()
    collected: List[Dict[str, Any]] = []

    # 1. Remotive Live Feed (Active developer roles)
    try:
        req = urllib.request.Request(
            "https://remotive.com/api/remote-jobs?limit=30",
            headers={"User-Agent": "ResumeAI-LiveFeed-Engine/1.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            for item in data.get("jobs", []):
                title = item.get("title", "").strip()
                if not title:
                    continue

                desc = _clean_html(item.get("description", ""))
                seniority, min_exp = _infer_seniority(title)

                raw_tags = [normalize_skill(t) for t in item.get("tags", []) if t.strip()]
                nlp_skills = extract_skills_nlp(f"{title} {desc}", nlp)
                all_skills = list(dict.fromkeys(raw_tags + nlp_skills))

                req_skills = all_skills[:5] if len(all_skills) >= 5 else (all_skills or ["software development", "problem solving"])
                pref_skills = all_skills[5:10] if len(all_skills) > 5 else []

                loc = item.get("candidate_required_location", "Remote") or "Remote"

                collected.append({
                    "title": title,
                    "company": item.get("company_name", "Tech Enterprise"),
                    "location": loc,
                    "job_type": "Remote",
                    "seniority_level": seniority,
                    "min_experience": min_exp,
                    "description": desc,
                    "required_skills": req_skills,
                    "preferred_skills": pref_skills,
                    "source": "Remotive Live Feed",
                    "openings_count": 1
                })
    except Exception as e:
        logger.warning(f"Remotive feed fetch notice: {e}")

    # 2. Arbeitnow Live Feed (EU/Global tech roles)
    try:
        req2 = urllib.request.Request(
            "https://www.arbeitnow.com/api/job-board-api",
            headers={"User-Agent": "ResumeAI-LiveFeed-Engine/1.0"}
        )
        with urllib.request.urlopen(req2, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            for item in data.get("data", [])[:25]:
                title = item.get("title", "").strip()
                if not title:
                    continue

                desc = _clean_html(item.get("description", ""))
                seniority, min_exp = _infer_seniority(title)

                raw_tags = [normalize_skill(t) for t in item.get("tags", []) if t.strip()]
                nlp_skills = extract_skills_nlp(f"{title} {desc}", nlp)
                all_skills = list(dict.fromkeys(raw_tags + nlp_skills))

                req_skills = all_skills[:5] if len(all_skills) >= 5 else (all_skills or ["software development", "problem solving"])
                pref_skills = all_skills[5:10] if len(all_skills) > 5 else []

                is_remote = item.get("remote", False)
                loc = item.get("location", "Remote") or ("Remote" if is_remote else "Hybrid")

                collected.append({
                    "title": title,
                    "company": item.get("company_name", "Global Partner"),
                    "location": loc,
                    "job_type": "Remote" if is_remote else "Hybrid",
                    "seniority_level": seniority,
                    "min_experience": min_exp,
                    "description": desc,
                    "required_skills": req_skills,
                    "preferred_skills": pref_skills,
                    "source": "Arbeitnow Live Feed",
                    "openings_count": 1
                })
    except Exception as e:
        logger.warning(f"Arbeitnow feed fetch notice: {e}")

    return collected[:limit]

