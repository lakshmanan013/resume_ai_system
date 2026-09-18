"""
AI Skill Matching Engine.

Implements dual-method AI matching with explainable weighted blending:
1. Sentence Embeddings (Semantic Matching):
   - Uses sentence-transformers (all-MiniLM-L6-v2) to embed candidate skills and job descriptions.
   - Computes cosine similarity to detect semantic proximity (e.g. 'Node.js' <-> 'backend JavaScript').
   - In-memory caching for job requirement embeddings.
2. TF-IDF + Cosine Similarity (Fast Baseline Fallback):
   - Uses scikit-learn's TfidfVectorizer for n-gram textual similarity.
   - Used when sentence-transformers is offline or loading.
3. Exact & Normalized Required Skill Coverage:
   - Measures direct qualification coverage against mandatory skills.
4. Experience Fit Score:
   - Compares candidate years of experience against job seniority expectations.

Final Score formula (Config tunable):
  score = 0.60 * semantic_similarity + 0.30 * exact_coverage + 0.10 * experience_fit
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from config import Config
from skills_data import normalize_skill

logger = logging.getLogger(__name__)

# Global cache for sentence embedding models and job vector representations
_EMBEDDING_MODEL = None
_EMBEDDING_MODEL_LOADED = False
_JOB_EMBEDDING_CACHE: Dict[str, Any] = {}


def get_embedding_model():
    """
    Lazily loads the SentenceTransformer model with error logging.
    Gracefully returns None if sentence-transformers is unavailable or fails to load.
    """
    global _EMBEDDING_MODEL, _EMBEDDING_MODEL_LOADED
    if _EMBEDDING_MODEL_LOADED:
        return _EMBEDDING_MODEL

    try:
        from sentence_transformers import SentenceTransformer
        logger.info(f"Loading SentenceTransformer model '{Config.EMBEDDING_MODEL_NAME}'...")
        _EMBEDDING_MODEL = SentenceTransformer(Config.EMBEDDING_MODEL_NAME)
        logger.info("SentenceTransformer model loaded successfully.")
    except Exception as exc:
        logger.warning(
            f"SentenceTransformer could not be loaded ({exc}). "
            "Gracefully degrading to TF-IDF vectorization and keyword coverage."
        )
        _EMBEDDING_MODEL = None

    _EMBEDDING_MODEL_LOADED = True
    return _EMBEDDING_MODEL


def normalize_skill_set(skills: List[str]) -> set:
    """Standardizes list of skill strings into a set of canonical names."""
    if not skills:
        return set()
    return {normalize_skill(s) for s in skills if s and s.strip()}


def compute_tfidf_similarity(resume_text: str, job_text: str) -> float:
    """
    Computes baseline TF-IDF cosine similarity between resume text and job specification.
    Returns percentage score between 0.0 and 100.0.
    """
    clean_resume = (resume_text or "").strip()
    clean_job = (job_text or "").strip()

    if not clean_resume or not clean_job:
        return 0.0

    try:
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", max_features=5000)
        tfidf_matrix = vectorizer.fit_transform([clean_resume, clean_job])
        sim_matrix = cosine_similarity(tfidf_matrix)
        sim = float(sim_matrix[0, 1])
        return round(float(np.clip(sim * 100.0, 0.0, 100.0)), 2)
    except Exception as e:
        logger.debug(f"TF-IDF similarity calculation error: {e}")
        return 0.0


def compute_semantic_similarity(candidate_skills: List[str], required_skills: List[str],
                                preferred_skills: Optional[List[str]] = None,
                                job_id: Optional[int] = None) -> Optional[float]:
    """
    Computes semantic cosine similarity using sentence embeddings.
    Caches job requirement vectors to make repeated recommendation queries blazing fast.
    Returns percentage score 0.0 to 100.0, or None if embedding model is not available.
    """
    model = get_embedding_model()
    if model is None:
        return None

    if not candidate_skills:
        return 0.0

    candidate_text = "Proficient in technical skills: " + ", ".join(sorted(candidate_skills))

    # Construct and cache job text representation
    req = sorted(required_skills or [])
    pref = sorted(preferred_skills or [])
    cache_key = f"job_{job_id}_{'_'.join(req)}_{'_'.join(pref)}"

    try:
        candidate_vector = model.encode([candidate_text], normalize_embeddings=True)

        if cache_key in _JOB_EMBEDDING_CACHE:
            job_vector = _JOB_EMBEDDING_CACHE[cache_key]
        else:
            job_text = "Required skills: " + ", ".join(req)
            if pref:
                job_text += ". Preferred bonus skills: " + ", ".join(pref)
            job_vector = model.encode([job_text], normalize_embeddings=True)
            _JOB_EMBEDDING_CACHE[cache_key] = job_vector

        sim = float(np.dot(candidate_vector[0], job_vector[0]))
        # Baseline noise threshold for all-MiniLM-L6-v2 on keyword lists
        if sim <= 0.35:
            scaled = 0.0
        else:
            scaled = min(100.0, ((sim - 0.35) / 0.65) * 100.0)
        return round(scaled, 2)
    except Exception as e:
        logger.warning(f"Error computing semantic embedding similarity: {e}")
        return None


def generate_natural_language_explanation(score: float, matched_req: List[str],
                                         missing_req: List[str], matched_pref: List[str],
                                         experience_ok: Optional[bool],
                                         cand_exp: Optional[float],
                                         job_min_exp: Optional[float],
                                         scoring_mode: str) -> str:
    """
    Synthesizes a clear, natural-language explanation of the match score.
    Helps candidates and recruiters understand why a profile received its rating.
    """
    parts = []

    # 1. Skill evaluation
    if matched_req and not missing_req:
        parts.append(f"Outstanding match: 100% coverage of core requirements ({', '.join(matched_req[:4])})")
    elif matched_req:
        parts.append(f"Strong match on core skills ({', '.join(matched_req[:3])})")
    else:
        parts.append("Low direct overlap on core technical requirements")

    # 2. Gaps and preferred bonuses
    if missing_req:
        parts.append(f"missing key skill(s): {', '.join(missing_req[:3])}")
    if matched_pref:
        parts.append(f"bonus points for preferred competency in {', '.join(matched_pref[:2])}")

    # 3. Seniority fit
    if experience_ok is True:
        parts.append(f"candidate meets experience requirement ({cand_exp} yrs vs {job_min_exp}+ yrs expected)")
    elif experience_ok is False:
        parts.append(f"role typically seeks {job_min_exp}+ yrs (candidate has {cand_exp or 0} yrs)")

    # 4. Engine attribution
    if scoring_mode == "semantic_embeddings":
        engine_tag = "Evaluated via semantic neural embeddings"
    elif scoring_mode == "tfidf_fallback":
        engine_tag = "Evaluated via TF-IDF lexical cosine similarity"
    else:
        engine_tag = "Evaluated via skill taxonomy overlap"

    explanation = "; ".join(parts).capitalize() + f". ({engine_tag})"
    return explanation


def compute_match(candidate_skills: List[str],
                  job_required_skills: List[str],
                  job_preferred_skills: Optional[List[str]] = None,
                  candidate_experience_years: Optional[float] = None,
                  job_min_experience: Optional[float] = None,
                  resume_raw_text: Optional[str] = None,
                  job_description: Optional[str] = None,
                  job_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Main matching algorithm blending semantic similarity, exact skill coverage,
    and experience alignment into a unified 0-100 score.
    """
    candidate = normalize_skill_set(candidate_skills)
    required = normalize_skill_set(job_required_skills)
    preferred = normalize_skill_set(job_preferred_skills or [])

    matched_required = sorted(list(candidate & required))
    matched_preferred = sorted(list(candidate & preferred))
    missing_required = sorted(list(required - candidate))
    extra_skills = sorted(list(candidate - required - preferred))

    # 1. Exact Skill Coverage Calculation
    req_coverage = (len(matched_required) / len(required) * 100.0) if required else 100.0
    pref_coverage = (len(matched_preferred) / len(preferred) * 100.0) if preferred else 100.0
    skill_coverage_score = (req_coverage * 0.8) + (pref_coverage * 0.2) if (required and preferred) else req_coverage

    # 2. Experience Fit Calculation
    experience_fit = True
    experience_score = 100.0
    if job_min_experience is not None and job_min_experience > 0:
        c_exp = candidate_experience_years if candidate_experience_years is not None else 0.0
        if c_exp >= job_min_experience:
            experience_fit = True
            experience_score = 100.0
        else:
            experience_fit = False
            experience_score = max(0.0, min(90.0, (c_exp / job_min_experience) * 100.0))
    elif candidate_experience_years is not None and job_min_experience is None:
        experience_fit = True
        experience_score = 100.0
    else:
        experience_score = 0.0 if (not matched_required and not matched_preferred) else 100.0

    # 3. Semantic Similarity or TF-IDF Fallback
    semantic_sim = compute_semantic_similarity(
        list(candidate), list(required), list(preferred), job_id=job_id
    )

    if semantic_sim is not None:
        scoring_mode = "semantic_embeddings"
        eff_semantic = max(semantic_sim, skill_coverage_score)
        final_score = (
            (Config.WEIGHT_SEMANTIC * eff_semantic) +
            (Config.WEIGHT_REQUIRED_SKILLS * skill_coverage_score) +
            (Config.WEIGHT_EXPERIENCE * experience_score)
        )
    else:
        # Fallback to TF-IDF
        resume_content = resume_raw_text or " ".join(candidate)
        job_content = job_description or (" ".join(required) + " " + " ".join(preferred))
        tfidf_sim = compute_tfidf_similarity(resume_content, job_content)

        if tfidf_sim > 0.0:
            scoring_mode = "tfidf_fallback"
            final_score = (
                (Config.FALLBACK_WEIGHT_TFIDF * tfidf_sim) +
                (Config.FALLBACK_WEIGHT_REQUIRED_SKILLS * skill_coverage_score) +
                (Config.FALLBACK_WEIGHT_EXPERIENCE * experience_score)
            )
        else:
            scoring_mode = "keyword_fallback"
            final_score = (0.80 * skill_coverage_score) + (0.20 * experience_score)

    # Zero match guard: If candidate matches 0 required skills and 0 preferred skills and 0 semantic similarity
    if not candidate or (not matched_required and not matched_preferred and (semantic_sim is None or semantic_sim == 0.0)):
        final_score = 0.0

    final_score = float(np.clip(final_score, 0.0, 100.0))

    # 4. Generate Natural Language Explanation
    explanation = generate_natural_language_explanation(
        score=round(final_score, 1),
        matched_req=matched_required,
        missing_req=missing_required,
        matched_pref=matched_preferred,
        experience_ok=experience_fit,
        cand_exp=candidate_experience_years,
        job_min_exp=job_min_experience,
        scoring_mode=scoring_mode
    )

    reasons = [
        f"Skill Coverage: {len(matched_required)} of {len(required)} required skills present ({round(req_coverage)}%)",
        f"Experience: {candidate_experience_years or 0} years (target: {job_min_experience or 0}+ years)",
        f"Matching Mode: {scoring_mode.replace('_', ' ').title()}"
    ]

    return {
        "score": round(final_score, 1),
        "matched_skills": sorted(list(set(matched_required + matched_preferred))),
        "matched_required": matched_required,
        "matched_preferred": matched_preferred,
        "missing_skills": missing_required,
        "missing_ats_keywords": missing_required,
        "extra_skills": extra_skills,
        "experience_ok": experience_fit,
        "experience_fit": experience_fit,  # Alias for prompt spec
        "explanation": explanation,
        "scoring_mode": scoring_mode,
        "matched_count": len(matched_required) + len(matched_preferred),
        "total_skills_count": len(required) + len(preferred),
        "match_reasons": reasons,
        "breakdown": {
            "semantic_score": round(semantic_sim, 1) if semantic_sim is not None else None,
            "skill_coverage_score": round(skill_coverage_score, 1),
            "experience_score": round(experience_score, 1),
        }
    }


def rank_jobs(candidate_skills: List[str],
              jobs: List[Dict[str, Any]],
              candidate_experience_years: Optional[float] = None,
              threshold: float = 0.0,
              resume_raw_text: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Ranks a collection of job postings against candidate skills.
    Returns jobs annotated with match scores and explanations, sorted descending by match score.
    """
    ranked = []
    for job in jobs:
        match_result = compute_match(
            candidate_skills=candidate_skills,
            job_required_skills=job.get("required_skills") or job.get("required_skills_json") or [],
            job_preferred_skills=job.get("preferred_skills") or job.get("preferred_skills_json") or [],
            candidate_experience_years=candidate_experience_years,
            job_min_experience=job.get("min_experience", 0.0),
            resume_raw_text=resume_raw_text,
            job_description=job.get("description", ""),
            job_id=job.get("id")
        )

        if match_result["score"] >= threshold:
            ranked.append({**job, **match_result})

    ranked.sort(key=lambda j: j["score"], reverse=True)
    return ranked
