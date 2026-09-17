"""
AI Skill Matching Module.

Compares a candidate's extracted skill set against a job's required
skills, computes a weighted percentage match score, and identifies
missing skills / gaps. Also folds in a small experience-fit bonus so
two candidates with identical skills but different seniority don't
score identically.
"""


def normalize(skills):
    return {s.strip().lower() for s in skills if s and s.strip()}


def compute_match(candidate_skills, job_required_skills, job_preferred_skills=None,
                   candidate_experience_years=None, job_min_experience=None):
    """
    Returns a dict with:
      score (0-100), matched_skills, missing_skills, extra_skills,
      experience_ok (bool or None if unknown)
    Weighting: required skills = 80% of score, preferred skills = 20%.
    """
    candidate = normalize(candidate_skills)
    required = normalize(job_required_skills)
    preferred = normalize(job_preferred_skills or [])

    matched_required = candidate & required
    matched_preferred = candidate & preferred
    missing_required = required - candidate
    extra_skills = candidate - required - preferred

    required_score = (len(matched_required) / len(required) * 100) if required else 100.0
    preferred_score = (len(matched_preferred) / len(preferred) * 100) if preferred else 100.0

    if required and preferred:
        overall = required_score * 0.8 + preferred_score * 0.2
    elif required:
        overall = required_score
    elif preferred:
        overall = preferred_score
    else:
        overall = 100.0

    experience_ok = None
    if job_min_experience is not None and candidate_experience_years is not None:
        experience_ok = candidate_experience_years >= job_min_experience
        # Small penalty if under-experienced
        if not experience_ok:
            overall = overall - 10

    overall = max(0.0, min(100.0, overall))

    # Generate Naukri / Shine style match highlights
    reasons = []
    if matched_required:
        reasons.append(f"Matches {len(matched_required)}/{len(required)} core required skills: {', '.join(sorted(matched_required)[:3])}")
    if matched_preferred:
        reasons.append(f"Bonus: Includes preferred skills ({', '.join(sorted(matched_preferred)[:2])})")
    if experience_ok is True:
        reasons.append(f"Experience fit: {candidate_experience_years} yrs meets the {job_min_experience}+ yrs criteria")
    elif experience_ok is False:
        reasons.append(f"Notice: Role typically looks for {job_min_experience}+ yrs (detected: {candidate_experience_years or 0} yrs)")

    return {
        "score": round(overall, 1),
        "matched_skills": sorted(matched_required | matched_preferred),
        "matched_required": sorted(matched_required),
        "matched_preferred": sorted(matched_preferred),
        "missing_skills": sorted(missing_required),
        "missing_ats_keywords": sorted(missing_required),
        "extra_skills": sorted(extra_skills),
        "experience_ok": experience_ok,
        "matched_count": len(matched_required | matched_preferred),
        "total_skills_count": len(required | preferred),
        "match_reasons": reasons,
    }


def rank_jobs(candidate_skills, jobs, candidate_experience_years=None, threshold=0):
    """
    jobs: list of dicts each with at least id, title, company,
    required_skills (list), preferred_skills (list), min_experience.
    Returns jobs annotated with match info, sorted by score desc,
    filtered to those >= threshold.
    """
    results = []
    for job in jobs:
        match = compute_match(
            candidate_skills,
            job.get("required_skills", []),
            job.get("preferred_skills", []),
            candidate_experience_years,
            job.get("min_experience"),
        )
        if match["score"] >= threshold:
            results.append({**job, **match})
    results.sort(key=lambda j: j["score"], reverse=True)
    return results
