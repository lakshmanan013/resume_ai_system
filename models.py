import io
import csv
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask import current_app
from database import get_db
from skills_data import normalize_skill


# =============================================================================
# 1. Users & Authentication
# =============================================================================

def create_user(name, email, password, role="user"):
    db = get_db()
    db.execute(
        "INSERT INTO users (name, email, password_hash, role, is_active, failed_attempts, created_at) "
        "VALUES (?, ?, ?, ?, 1, 0, ?)",
        (name.strip(), email.strip().lower(), generate_password_hash(password), role, datetime.now(timezone.utc).isoformat()),
    )
    db.commit()


def get_user_by_email(email):
    return get_db().execute("SELECT * FROM users WHERE lower(email) = ?", (email.strip().lower(),)).fetchone()


def get_user_by_id(user_id):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def verify_password(user_row, password):
    if not user_row:
        return False
    return check_password_hash(user_row["password_hash"], password)


def set_password(user_id, new_password):
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (generate_password_hash(new_password), user_id))
    db.commit()


def list_users(search_term=None):
    db = get_db()
    if search_term:
        term = f"%{search_term.strip().lower()}%"
        return db.execute(
            "SELECT * FROM users WHERE lower(name) LIKE ? OR lower(email) LIKE ? ORDER BY created_at DESC",
            (term, term)
        ).fetchall()
    return db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()


def set_user_active(user_id, is_active):
    db = get_db()
    db.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))
    db.commit()


def update_user(user_id, name, email, role):
    db = get_db()
    db.execute("UPDATE users SET name = ?, email = ?, role = ? WHERE id = ?",
               (name.strip(), email.strip().lower(), role, user_id))
    db.commit()


# Rate Limiting & Account Lockout
def is_account_locked(user_row) -> bool:
    """Checks whether the user account is currently locked due to failed attempts."""
    if not user_row:
        return False
    locked_until_str = user_row["locked_until"]
    if not locked_until_str:
        return False
    try:
        locked_until = datetime.fromisoformat(locked_until_str)
        if locked_until > datetime.now(timezone.utc):
            return True
    except Exception:
        pass
    return False


def record_login_failure(email: str, max_attempts: int = 5, lockout_minutes: int = 15):
    """Increments failed login attempts and locks account if threshold exceeded."""
    db = get_db()
    user = get_user_by_email(email)
    if not user:
        return

    new_failures = (user["failed_attempts"] or 0) + 1
    locked_until = None
    if new_failures >= max_attempts:
        locked_until = (datetime.now(timezone.utc) + timedelta(minutes=lockout_minutes)).isoformat()

    db.execute(
        "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
        (new_failures, locked_until, user["id"])
    )
    db.commit()


def reset_login_failures(user_id: int):
    """Clears failed login attempts after successful authentication."""
    db = get_db()
    db.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user_id,))
    db.commit()


# Password Reset Token Helpers (Module 1)
def generate_reset_token(email: str) -> str:
    """Generates a secure, time-limited cryptographic token for password reset."""
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    token = serializer.dumps(email.strip().lower(), salt="password-reset-salt")
    db = get_db()
    user = get_user_by_email(email)
    if user:
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=current_app.config.get("RESET_TOKEN_MAX_AGE", 3600))).isoformat()
        db.execute("UPDATE users SET reset_token = ?, reset_token_expiry = ? WHERE id = ?", (token, expiry, user["id"]))
        db.commit()
    return token


def verify_reset_token(token: str, max_age: int = 3600) -> Optional[dict]:
    """Verifies a password reset token and returns the user record if valid."""
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"])
    try:
        email = serializer.loads(token, salt="password-reset-salt", max_age=max_age)
    except (SignatureExpired, BadSignature):
        return None

    user = get_user_by_email(email)
    if not user or user["reset_token"] != token:
        return None
    return user


def reset_user_password(user_id: int, new_password: str):
    """Updates password and invalidates reset token."""
    db = get_db()
    db.execute(
        "UPDATE users SET password_hash = ?, reset_token = NULL, reset_token_expiry = NULL, "
        "failed_attempts = 0, locked_until = NULL WHERE id = ?",
        (generate_password_hash(new_password), user_id)
    )
    db.commit()


# =============================================================================
# 2. Resumes (Ingestion, Structured JSON, Versioning)
# =============================================================================

def save_resume(user_id, filename, filepath, parsed, is_confirmed=0):
    db = get_db()
    # Compute version number
    current_ver = db.execute(
        "SELECT COALESCE(MAX(version), 0) AS max_ver FROM resumes WHERE user_id = ?", (user_id,)
    ).fetchone()["max_ver"]
    new_version = current_ver + 1

    skills = [normalize_skill(s) for s in parsed.get("skills", [])]
    skills_json = json.dumps(skills)
    parsed_json = json.dumps(parsed)

    cur = db.execute(
        "INSERT INTO resumes (user_id, filename, filepath, raw_text, parsed_name, email, phone, "
        "education, skills, parsed_json, skills_json, experience_years, version, is_confirmed, uploaded_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, filename, filepath, parsed.get("raw_text", ""), parsed.get("name", "Candidate"),
         parsed.get("email"), parsed.get("phone"), json.dumps(parsed.get("education", [])),
         skills_json, parsed_json, skills_json, parsed.get("experience_years", 0.0),
         new_version, int(is_confirmed), datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    return cur.lastrowid


def get_latest_resume(user_id):
    return get_db().execute(
        "SELECT * FROM resumes WHERE user_id = ? ORDER BY uploaded_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()


def get_resume(resume_id):
    return get_db().execute("SELECT * FROM resumes WHERE id = ?", (resume_id,)).fetchone()


def list_user_resumes(user_id):
    return get_db().execute(
        "SELECT * FROM resumes WHERE user_id = ? ORDER BY version DESC", (user_id,)
    ).fetchall()


def list_all_resumes(search_term=None):
    db = get_db()
    q = ("SELECT resumes.*, users.name AS user_name, users.email AS user_email "
         "FROM resumes JOIN users ON resumes.user_id = users.id ")
    params = []
    if search_term:
        q += "WHERE lower(users.name) LIKE ? OR lower(users.email) LIKE ? OR lower(resumes.filename) LIKE ? "
        t = f"%{search_term.strip().lower()}%"
        params.extend([t, t, t])
    q += "ORDER BY resumes.uploaded_at DESC"
    return db.execute(q, params).fetchall()


def resume_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["education"] = json.loads(d.get("education") or "[]")
    d["skills"] = json.loads(d.get("skills_json") or d.get("skills") or "[]")
    d["skills_json"] = d["skills"]
    d["parsed_json"] = json.loads(d.get("parsed_json") or "{}")
    d["version"] = d.get("version") or 1
    d["is_confirmed"] = bool(d.get("is_confirmed", 0))
    return d


def confirm_resume(resume_id: int, user_id: Optional[int] = None):
    db = get_db()
    if user_id:
        db.execute("UPDATE resumes SET is_confirmed = 1 WHERE id = ? AND user_id = ?", (resume_id, user_id))
    else:
        db.execute("UPDATE resumes SET is_confirmed = 1 WHERE id = ?", (resume_id,))
    db.commit()


def update_resume_data(resume_id, user_id, skills=None, experience_years=None, name=None, email=None, phone=None):
    db = get_db()
    if user_id is not None:
        row = db.execute("SELECT id FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id)).fetchone()
        if not row:
            return None

    updates = []
    params = []
    if skills is not None:
        cleaned_skills = sorted(list({normalize_skill(s) for s in skills if s and s.strip()}))
        s_json = json.dumps(cleaned_skills)
        updates.append("skills = ?")
        params.append(s_json)
        updates.append("skills_json = ?")
        params.append(s_json)
    if experience_years is not None:
        updates.append("experience_years = ?")
        params.append(float(experience_years) if str(experience_years).strip() != "" else 0.0)
    if name is not None:
        updates.append("parsed_name = ?")
        params.append(name.strip())
    if email is not None:
        updates.append("email = ?")
        params.append(email.strip())
    if phone is not None:
        updates.append("phone = ?")
        params.append(phone.strip())

    # Mark confirmed on user edit
    updates.append("is_confirmed = 1")

    if updates:
        params.append(resume_id)
        query = f"UPDATE resumes SET {', '.join(updates)} WHERE id = ?"
        db.execute(query, params)
        db.commit()

    return resume_to_dict(get_resume(resume_id))


# =============================================================================
# 3. Jobs & Multi-Faceted Recommendations
# =============================================================================

def create_job(title, company, location, description, required_skills, preferred_skills, min_experience,
               job_type="Full-Time", seniority_level="Mid-Level", openings_count=1, source="Direct Portal"):
    db = get_db()
    req_clean = sorted(list({normalize_skill(s) for s in required_skills if s and s.strip()}))
    pref_clean = sorted(list({normalize_skill(s) for s in preferred_skills if s and s.strip()}))

    req_json = json.dumps(req_clean)
    pref_json = json.dumps(pref_clean)

    db.execute(
        "INSERT INTO jobs (title, company, location, description, required_skills, preferred_skills, "
        "required_skills_json, preferred_skills_json, min_experience, job_type, seniority_level, "
        "openings_count, source, is_active, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
        (title.strip(), company.strip(), location.strip(), description.strip(),
         req_json, pref_json, req_json, pref_json, float(min_experience or 0),
         job_type, seniority_level, int(openings_count or 1), source,
         datetime.now(timezone.utc).isoformat()),
    )
    db.commit()


def update_job(job_id, title, company, location, description, required_skills, preferred_skills, min_experience,
               job_type="Full-Time", seniority_level="Mid-Level", openings_count=1, source="Direct Portal"):
    db = get_db()
    req_clean = sorted(list({normalize_skill(s) for s in required_skills if s and s.strip()}))
    pref_clean = sorted(list({normalize_skill(s) for s in preferred_skills if s and s.strip()}))
    req_json = json.dumps(req_clean)
    pref_json = json.dumps(pref_clean)

    db.execute(
        "UPDATE jobs SET title=?, company=?, location=?, description=?, required_skills=?, preferred_skills=?, "
        "required_skills_json=?, preferred_skills_json=?, min_experience=?, job_type=?, seniority_level=?, "
        "openings_count=?, source=? WHERE id=?",
        (title.strip(), company.strip(), location.strip(), description.strip(),
         req_json, pref_json, req_json, pref_json, float(min_experience or 0),
         job_type, seniority_level, int(openings_count or 1), source, job_id),
    )
    db.commit()


def delete_job(job_id):
    db = get_db()
    db.execute("DELETE FROM matches WHERE job_id = ?", (job_id,))
    db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    db.commit()


def set_job_active(job_id, is_active):
    db = get_db()
    db.execute("UPDATE jobs SET is_active = ? WHERE id = ?", (int(is_active), job_id))
    db.commit()


def get_job(job_id):
    return get_db().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def list_jobs(active_only=True, search_query=None, location=None, job_type=None, seniority=None):
    """
    Retrieves jobs with multi-faceted filtering and fuzzy search across title, company, and description.
    """
    db = get_db()
    clauses = []
    params = []

    if active_only:
        clauses.append("is_active = 1")

    if search_query:
        term = f"%{search_query.strip().lower()}%"
        clauses.append("(lower(title) LIKE ? OR lower(company) LIKE ? OR lower(description) LIKE ?)")
        params.extend([term, term, term])

    if location:
        clauses.append("lower(location) LIKE ?")
        params.append(f"%{location.strip().lower()}%")

    if job_type and job_type.lower() != "all":
        clauses.append("lower(job_type) = ?")
        params.append(job_type.strip().lower())

    if seniority and seniority.lower() != "all":
        clauses.append("lower(seniority_level) = ?")
        params.append(seniority.strip().lower())

    q = "SELECT * FROM jobs"
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY created_at DESC"

    return db.execute(q, params).fetchall()


def job_to_dict(row: Any) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    d["required_skills"] = json.loads(d.get("required_skills_json") or d.get("required_skills") or "[]")
    d["preferred_skills"] = json.loads(d.get("preferred_skills_json") or d.get("preferred_skills") or "[]")
    d["required_skills_json"] = d["required_skills"]
    d["preferred_skills_json"] = d["preferred_skills"]
    d["job_type"] = d.get("job_type") or "Full-Time"
    d["seniority_level"] = d.get("seniority_level") or "Mid-Level"
    d["openings_count"] = d.get("openings_count") or 1
    d["source"] = d.get("source") or "manual"
    d["external_id"] = d.get("external_id")
    d["source_url"] = d.get("source_url")
    d["salary_min"] = d.get("salary_min")
    d["salary_max"] = d.get("salary_max")
    d["posted_at"] = d.get("posted_at")
    d["last_synced_at"] = d.get("last_synced_at")
    d["is_active"] = bool(d.get("is_active", 1))
    return d


def upsert_job(job_data: dict) -> Optional[dict[str, Any]]:
    """
    UPSERTs a job record into the jobs table keyed on (source, external_id).
    If source and external_id match an existing record, updates it.
    Otherwise inserts a new record. Prevents duplicates on re-sync.
    """
    db = get_db()
    source = (job_data.get("source") or "manual").strip()
    external_id = str(job_data.get("external_id") or "").strip() or None

    title = (job_data.get("title") or "").strip()
    company = (job_data.get("company") or "").strip()
    location = (job_data.get("location") or "Remote").strip()
    description = (job_data.get("description") or "").strip()

    req_skills = job_data.get("required_skills", [])
    pref_skills = job_data.get("preferred_skills", [])
    req_clean = sorted(list({normalize_skill(s) for s in req_skills if s and s.strip()}))
    pref_clean = sorted(list({normalize_skill(s) for s in pref_skills if s and s.strip()}))
    req_json = json.dumps(req_clean)
    pref_json = json.dumps(pref_clean)

    raw_exp = job_data.get("min_experience", 0)
    try:
        min_experience = float(raw_exp)
    except (ValueError, TypeError):
        min_experience = 0.0

    job_type = job_data.get("job_type", "Full-Time")
    seniority_level = job_data.get("seniority_level", "Mid-Level")
    openings_count = int(job_data.get("openings_count") or 1)
    source_url = job_data.get("source_url")
    salary_min = job_data.get("salary_min")
    salary_max = job_data.get("salary_max")
    posted_at = job_data.get("posted_at")
    now_iso = datetime.now(timezone.utc).isoformat()

    existing = None
    if external_id:
        existing = db.execute(
            "SELECT id FROM jobs WHERE source = ? AND external_id = ?",
            (source, external_id)
        ).fetchone()
    if not existing:
        existing = db.execute(
            "SELECT id FROM jobs WHERE title = ? AND company = ?",
            (title, company)
        ).fetchone()

    is_new = False
    if existing:
        is_new = False
        job_id = existing["id"]
        db.execute(
            "UPDATE jobs SET title=?, company=?, location=?, description=?, required_skills=?, preferred_skills=?, "
            "required_skills_json=?, preferred_skills_json=?, min_experience=?, job_type=?, seniority_level=?, "
            "openings_count=?, source=?, external_id=?, source_url=?, salary_min=?, salary_max=?, posted_at=?, "
            "last_synced_at=?, is_active=1 WHERE id=?",
            (title, company, location, description, req_json, pref_json, req_json, pref_json,
             min_experience, job_type, seniority_level, openings_count, source, external_id,
             source_url, salary_min, salary_max, posted_at, now_iso, job_id)
        )
    else:
        is_new = True
        db.execute(
            "INSERT INTO jobs (title, company, location, description, required_skills, preferred_skills, "
            "required_skills_json, preferred_skills_json, min_experience, job_type, seniority_level, "
            "openings_count, source, external_id, source_url, salary_min, salary_max, posted_at, "
            "last_synced_at, is_active, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)",
            (title, company, location, description, req_json, pref_json, req_json, pref_json,
             min_experience, job_type, seniority_level, openings_count, source, external_id,
             source_url, salary_min, salary_max, posted_at, now_iso, now_iso)
        )
        row = None
        if external_id:
            row = db.execute("SELECT id FROM jobs WHERE source = ? AND external_id = ?", (source, external_id)).fetchone()
        if not row:
            row = db.execute("SELECT id FROM jobs WHERE title = ? AND company = ? ORDER BY id DESC", (title, company)).fetchone()
        job_id = row["id"] if row else None

    db.commit()
    updated_job = get_job(job_id) if job_id else None
    result = job_to_dict(updated_job)
    if result:
        result["is_new"] = is_new
    return result


def get_active_jobs_count() -> int:
    """Returns total count of currently active jobs."""
    db = get_db()
    row = db.execute("SELECT COUNT(*) AS total FROM jobs WHERE is_active = 1").fetchone()
    return int(row["total"]) if row else 0


def get_latest_active_jobs(limit: int = 15) -> list[dict[str, Any]]:
    """Returns the most recently posted or synced active jobs."""
    db = get_db()
    rows = db.execute(
        "SELECT * FROM jobs WHERE is_active = 1 ORDER BY last_synced_at DESC, id DESC LIMIT ?",
        (max(1, limit),)
    ).fetchall()
    return [d for r in rows if (d := job_to_dict(r)) is not None]


def soft_deactivate_stale_adzuna_jobs(active_external_ids: set, cutoff_days: int = 7) -> int:
    """
    Soft-deactivates jobs sourced from Adzuna that were not in the active external_ids set
    or whose last_synced_at is older than cutoff_days. Sets is_active = 0 to avoid breaking
    matches table foreign key references.
    """
    db = get_db()
    stale_count = 0
    rows = db.execute("SELECT id, external_id, last_synced_at FROM jobs WHERE source = 'adzuna' AND is_active = 1").fetchall()
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=cutoff_days)

    for r in rows:
        ext_id = str(r["external_id"]) if r["external_id"] is not None else ""
        is_stale = False
        if ext_id and ext_id not in active_external_ids:
            last_synced_str = r["last_synced_at"]
            if last_synced_str:
                try:
                    last_synced = datetime.fromisoformat(last_synced_str)
                    if last_synced < cutoff_time:
                        is_stale = True
                except Exception:
                    is_stale = True
            else:
                is_stale = True

        if is_stale:
            db.execute("UPDATE jobs SET is_active = 0 WHERE id = ?", (r["id"],))
            stale_count += 1

    if stale_count > 0:
        db.commit()
    return stale_count


def get_last_adzuna_sync_time() -> Optional[str]:
    """Retrieves the most recent last_synced_at timestamp for Adzuna jobs."""
    db = get_db()
    row = db.execute("SELECT MAX(last_synced_at) AS last_sync FROM jobs WHERE source = 'adzuna'").fetchone()
    if row and row["last_sync"]:
        return row["last_sync"]
    return None


def sync_live_jobs():
    """Syncs/refreshes the active jobs table with live real jobs from external feeds."""
    from database import sync_live_jobs_db
    db = get_db()
    return sync_live_jobs_db(db)



# =============================================================================
# 4. Matches & Audit Logging
# =============================================================================

def save_match(user_id, resume_id, job_id, score, matched_skills, missing_skills, explanation=None):
    db = get_db()
    m_json = json.dumps(matched_skills)
    miss_json = json.dumps(missing_skills)
    db.execute(
        "INSERT INTO matches (user_id, resume_id, job_id, score, matched_skills, missing_skills, "
        "matched_skills_json, missing_skills_json, explanation, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (user_id, resume_id, job_id, score, m_json, miss_json, m_json, miss_json,
         explanation or "", datetime.now(timezone.utc).isoformat()),
    )
    db.commit()


def bulk_save_matches(user_id, resume_id, ranked_jobs):
    db = get_db()
    db.execute("DELETE FROM matches WHERE user_id = ? AND resume_id = ?", (user_id, resume_id))
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for j in ranked_jobs:
        m_json = json.dumps(j.get("matched_skills", []))
        miss_json = json.dumps(j.get("missing_skills", []))
        rows.append((
            user_id, resume_id, j["id"], j["score"], m_json, miss_json,
            m_json, miss_json, j.get("explanation", ""), now
        ))

    db.executemany(
        "INSERT INTO matches (user_id, resume_id, job_id, score, matched_skills, missing_skills, "
        "matched_skills_json, missing_skills_json, explanation, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        rows
    )
    db.commit()


def list_all_matches(search_term=None):
    db = get_db()
    q = ("SELECT matches.*, users.name AS user_name, jobs.title AS job_title, "
         "jobs.company AS company FROM matches "
         "JOIN users ON matches.user_id = users.id "
         "JOIN jobs ON matches.job_id = jobs.id ")
    params = []
    if search_term:
        t = f"%{search_term.strip().lower()}%"
        q += "WHERE lower(users.name) LIKE ? OR lower(jobs.title) LIKE ? OR lower(jobs.company) LIKE ? "
        params.extend([t, t, t])
    q += "ORDER BY matches.created_at DESC LIMIT 200"
    return db.execute(q, params).fetchall()


# =============================================================================
# 5. Reports & Market Gap Analytics
# =============================================================================

def get_stats():
    db = get_db()
    stats = {}
    stats["total_users"] = db.execute("SELECT COUNT(*) c FROM users WHERE role='user'").fetchone()["c"]
    stats["active_users"] = db.execute("SELECT COUNT(*) c FROM users WHERE role='user' AND is_active=1").fetchone()["c"]
    stats["total_resumes"] = db.execute("SELECT COUNT(*) c FROM resumes").fetchone()["c"]
    stats["total_jobs"] = db.execute("SELECT COUNT(*) c FROM jobs WHERE is_active=1").fetchone()["c"]
    stats["total_matches"] = db.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    avg = db.execute("SELECT AVG(score) a FROM matches").fetchone()["a"]
    stats["avg_match_score"] = round(float(avg), 1) if avg is not None else 0

    # Top matched jobs
    top_raw = db.execute(
        "SELECT jobs.title, jobs.company, COUNT(*) as matches, AVG(matches.score) as avg_score "
        "FROM matches JOIN jobs ON matches.job_id = jobs.id "
        "GROUP BY matches.job_id, jobs.title, jobs.company ORDER BY matches DESC LIMIT 5"
    ).fetchall()
    stats["top_jobs"] = [
        {
            "title": r["title"],
            "company": r["company"],
            "matches": r["matches"],
            "avg_score": round(float(r.get("avg_score") or 0), 1)
        }
        for r in top_raw
    ]

    # Skill Market Gap Analysis: Most-Requested Job Skills vs Most-Common Candidate Skills
    stats["most_requested_skills"] = _get_most_requested_skills(db)
    stats["most_common_candidate_skills"] = _get_most_common_candidate_skills(db)
    stats["skill_gap_analysis"] = _get_skill_gap_comparison(stats["most_requested_skills"], stats["most_common_candidate_skills"])

    # Zero qualified candidate jobs (jobs with no matches >= 50%)
    stats["zero_match_jobs"] = [dict(row) for row in db.execute(
        "SELECT jobs.id, jobs.title, jobs.company, jobs.location "
        "FROM jobs WHERE is_active = 1 AND jobs.id NOT IN ("
        "  SELECT DISTINCT job_id FROM matches WHERE score >= 50"
        ") LIMIT 5"
    ).fetchall()]

    return stats


def _get_most_requested_skills(db, limit=10):
    rows = db.execute("SELECT required_skills_json, required_skills FROM jobs WHERE is_active = 1").fetchall()
    counts = {}
    for r in rows:
        skills = json.loads(r["required_skills_json"] or r["required_skills"] or "[]")
        for s in skills:
            can = normalize_skill(s)
            counts[can] = counts.get(can, 0) + 1
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"skill": s, "count": c} for s, c in top]


def _get_most_common_candidate_skills(db, limit=10):
    rows = db.execute("SELECT skills_json, skills FROM resumes").fetchall()
    counts = {}
    for r in rows:
        skills = json.loads(r["skills_json"] or r["skills"] or "[]")
        for s in skills:
            can = normalize_skill(s)
            counts[can] = counts.get(can, 0) + 1
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"skill": s, "count": c} for s, c in top]


def _get_skill_gap_comparison(requested_list, candidate_list):
    """Computes market surplus or deficit for key industry skills."""
    req_dict = {item["skill"]: item["count"] for item in requested_list}
    cand_dict = {item["skill"]: item["count"] for item in candidate_list}

    all_keys = set(req_dict.keys()) | set(cand_dict.keys())
    gaps = []
    for skill in all_keys:
        demand = req_dict.get(skill, 0)
        supply = cand_dict.get(skill, 0)
        deficit = demand - supply
        gaps.append({
            "skill": skill,
            "demand": demand,
            "supply": supply,
            "deficit": deficit,
            "status": "High Deficit" if deficit > 2 else ("Equilibrium" if abs(deficit) <= 2 else "High Supply")
        })
    gaps.sort(key=lambda x: x["deficit"], reverse=True)
    return gaps[:10]


def export_stats_csv() -> str:
    """Exports administrative system analytics and match metrics as CSV."""
    db = get_db()
    output = io.StringIO()
    writer = csv.writer(output)

    # 1. Matches Report
    writer.writerow(["=== MATCHES AUDIT LOG ==="])
    writer.writerow(["Match ID", "Candidate Name", "Candidate Email", "Job Title", "Company", "Match Score", "Matched Skills", "Missing Skills", "Explanation", "Timestamp"])

    matches = db.execute(
        "SELECT matches.id, users.name, users.email, jobs.title, jobs.company, matches.score, "
        "matches.matched_skills_json, matches.missing_skills_json, matches.explanation, matches.created_at "
        "FROM matches "
        "JOIN users ON matches.user_id = users.id "
        "JOIN jobs ON matches.job_id = jobs.id "
        "ORDER BY matches.created_at DESC"
    ).fetchall()

    for m in matches:
        writer.writerow([
            m["id"], m["name"], m["email"], m["title"], m["company"],
            m["score"], m["matched_skills_json"], m["missing_skills_json"],
            m["explanation"] or "", m["created_at"]
        ])

    writer.writerow([])
    writer.writerow(["=== ACTIVE JOBS INVENTORY ==="])
    writer.writerow(["Job ID", "Title", "Company", "Location", "Min Experience", "Job Type", "Seniority", "Required Skills", "Status"])

    jobs = db.execute("SELECT id, title, company, location, min_experience, job_type, seniority_level, required_skills_json, is_active FROM jobs").fetchall()
    for j in jobs:
        writer.writerow([
            j["id"], j["title"], j["company"], j["location"], j["min_experience"],
            j["job_type"], j["seniority_level"], j["required_skills_json"],
            "Active" if j["is_active"] else "Hidden"
        ])

    return output.getvalue()
