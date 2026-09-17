import json
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_db


# ---------- Users ----------

def create_user(name, email, password, role="user"):
    db = get_db()
    db.execute(
        "INSERT INTO users (name, email, password_hash, role, is_active, created_at) "
        "VALUES (?, ?, ?, ?, 1, ?)",
        (name, email, generate_password_hash(password), role, datetime.now(timezone.utc).isoformat()),
    )
    db.commit()


def get_user_by_email(email):
    return get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


def get_user_by_id(user_id):
    return get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def verify_password(user_row, password):
    return check_password_hash(user_row["password_hash"], password)


def set_password(user_id, new_password):
    db = get_db()
    db.execute("UPDATE users SET password_hash = ? WHERE id = ?",
               (generate_password_hash(new_password), user_id))
    db.commit()


def list_users():
    return get_db().execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()


def set_user_active(user_id, is_active):
    db = get_db()
    db.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))
    db.commit()


def update_user(user_id, name, email, role):
    db = get_db()
    db.execute("UPDATE users SET name = ?, email = ?, role = ? WHERE id = ?",
               (name, email, role, user_id))
    db.commit()


# ---------- Resumes ----------

def save_resume(user_id, filename, filepath, parsed):
    db = get_db()
    cur = db.execute(
        "INSERT INTO resumes (user_id, filename, filepath, raw_text, parsed_name, email, phone, "
        "education, skills, experience_years, uploaded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (user_id, filename, filepath, parsed["raw_text"], parsed["name"], parsed["email"],
         parsed["phone"], json.dumps(parsed["education"]), json.dumps(parsed["skills"]),
         parsed["experience_years"], datetime.now(timezone.utc).isoformat()),
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


def list_all_resumes():
    return get_db().execute(
        "SELECT resumes.*, users.name AS user_name, users.email AS user_email "
        "FROM resumes JOIN users ON resumes.user_id = users.id "
        "ORDER BY uploaded_at DESC"
    ).fetchall()


def resume_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["education"] = json.loads(d["education"] or "[]")
    d["skills"] = json.loads(d["skills"] or "[]")
    return d


def update_resume_data(resume_id, user_id, skills=None, experience_years=None, name=None, email=None, phone=None):
    db = get_db()
    # verify ownership if user_id is provided
    if user_id is not None:
        row = db.execute("SELECT id FROM resumes WHERE id = ? AND user_id = ?", (resume_id, user_id)).fetchone()
        if not row:
            return None

    updates = []
    params = []
    if skills is not None:
        updates.append("skills = ?")
        # Ensure clean lowercase unique skills list
        cleaned_skills = sorted(list({s.strip().lower() for s in skills if s and s.strip()}))
        params.append(json.dumps(cleaned_skills))
    if experience_years is not None:
        updates.append("experience_years = ?")
        params.append(float(experience_years) if experience_years != "" else None)
    if name is not None:
        updates.append("parsed_name = ?")
        params.append(name.strip())
    if email is not None:
        updates.append("email = ?")
        params.append(email.strip())
    if phone is not None:
        updates.append("phone = ?")
        params.append(phone.strip())

    if updates:
        params.extend([resume_id])
        query = f"UPDATE resumes SET {', '.join(updates)} WHERE id = ?"
        db.execute(query, params)
        db.commit()

    return resume_to_dict(get_resume(resume_id))


# ---------- Jobs ----------

def create_job(title, company, location, description, required_skills, preferred_skills, min_experience,
               job_type="Full-Time", openings_count=1, source="Direct Portal"):
    db = get_db()
    db.execute(
        "INSERT INTO jobs (title, company, location, description, required_skills, "
        "preferred_skills, min_experience, job_type, openings_count, source, is_active, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
        (title, company, location, description, json.dumps(required_skills),
         json.dumps(preferred_skills), min_experience, job_type, openings_count, source,
         datetime.now(timezone.utc).isoformat()),
    )
    db.commit()


def update_job(job_id, title, company, location, description, required_skills, preferred_skills, min_experience,
               job_type="Full-Time", openings_count=1, source="Direct Portal"):
    db = get_db()
    db.execute(
        "UPDATE jobs SET title=?, company=?, location=?, description=?, required_skills=?, "
        "preferred_skills=?, min_experience=?, job_type=?, openings_count=?, source=? WHERE id=?",
        (title, company, location, description, json.dumps(required_skills),
         json.dumps(preferred_skills), min_experience, job_type, openings_count, source, job_id),
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


def list_jobs(active_only=True):
    q = "SELECT * FROM jobs"
    if active_only:
        q += " WHERE is_active = 1"
    q += " ORDER BY created_at DESC"
    return get_db().execute(q).fetchall()


def job_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    d["required_skills"] = json.loads(d.get("required_skills") or "[]")
    d["preferred_skills"] = json.loads(d.get("preferred_skills") or "[]")
    d["job_type"] = d.get("job_type") or "Full-Time"
    d["openings_count"] = d.get("openings_count") or 1
    d["source"] = d.get("source") or "Direct Portal"
    return d


def sync_live_jobs():
    """Syncs/refreshes the active jobs table with real-world Naukri/Shine catalog jobs."""
    from database import SAMPLE_JOBS
    db = get_db()
    added_count = 0
    now = datetime.now(timezone.utc).isoformat()
    for job in SAMPLE_JOBS:
        existing = db.execute("SELECT id FROM jobs WHERE title = ? AND company = ?",
                              (job["title"], job["company"])).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO jobs (title, company, location, description, required_skills, "
                "preferred_skills, min_experience, job_type, openings_count, source, is_active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (job["title"], job["company"], job["location"], job["description"],
                 json.dumps(job["required_skills"]), json.dumps(job["preferred_skills"]),
                 job["min_experience"], job.get("job_type", "Full-Time"),
                 job.get("openings_count", 1), job.get("source", "Naukri Live Feed"), now),
            )
            added_count += 1
        else:
            db.execute(
                "UPDATE jobs SET job_type=?, openings_count=?, source=?, is_active=1 WHERE id=?",
                (job.get("job_type", "Full-Time"), job.get("openings_count", 1),
                 job.get("source", "Naukri Live Feed"), existing["id"])
            )
    db.commit()
    total_active = db.execute("SELECT COUNT(*) AS c FROM jobs WHERE is_active = 1").fetchone()["c"]
    return {"added": added_count, "total_active": total_active}


# ---------- Matches ----------

def save_match(user_id, resume_id, job_id, score, matched_skills, missing_skills):
    db = get_db()
    db.execute(
        "INSERT INTO matches (user_id, resume_id, job_id, score, matched_skills, missing_skills, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (user_id, resume_id, job_id, score, json.dumps(matched_skills),
         json.dumps(missing_skills), datetime.now(timezone.utc).isoformat()),
    )
    db.commit()


def bulk_save_matches(user_id, resume_id, ranked_jobs):
    db = get_db()
    db.execute("DELETE FROM matches WHERE user_id = ? AND resume_id = ?", (user_id, resume_id))
    now = datetime.now(timezone.utc).isoformat()
    db.executemany(
        "INSERT INTO matches (user_id, resume_id, job_id, score, matched_skills, missing_skills, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            (user_id, resume_id, j["id"], j["score"], json.dumps(j["matched_skills"]),
             json.dumps(j["missing_skills"]), now)
            for j in ranked_jobs
        ],
    )
    db.commit()


def list_all_matches():
    return get_db().execute(
        "SELECT matches.*, users.name AS user_name, jobs.title AS job_title, "
        "jobs.company AS company FROM matches "
        "JOIN users ON matches.user_id = users.id "
        "JOIN jobs ON matches.job_id = jobs.id "
        "ORDER BY matches.created_at DESC"
    ).fetchall()


# ---------- Reports ----------

def get_stats():
    db = get_db()
    stats = {}
    stats["total_users"] = db.execute("SELECT COUNT(*) c FROM users WHERE role='user'").fetchone()["c"]
    stats["active_users"] = db.execute("SELECT COUNT(*) c FROM users WHERE role='user' AND is_active=1").fetchone()["c"]
    stats["total_resumes"] = db.execute("SELECT COUNT(*) c FROM resumes").fetchone()["c"]
    stats["total_jobs"] = db.execute("SELECT COUNT(*) c FROM jobs WHERE is_active=1").fetchone()["c"]
    stats["total_matches"] = db.execute("SELECT COUNT(*) c FROM matches").fetchone()["c"]
    avg = db.execute("SELECT AVG(score) a FROM matches").fetchone()["a"]
    stats["avg_match_score"] = round(avg, 1) if avg else 0
    stats["top_jobs"] = [dict(row) for row in db.execute(
        "SELECT jobs.title, jobs.company, COUNT(*) as matches, AVG(matches.score) as avg_score "
        "FROM matches JOIN jobs ON matches.job_id = jobs.id "
        "GROUP BY matches.job_id ORDER BY matches DESC LIMIT 5"
    ).fetchall()]
    stats["top_missing_skills"] = _top_missing_skills(db)
    return stats


def _top_missing_skills(db):
    rows = db.execute("SELECT missing_skills FROM matches").fetchall()
    counts = {}
    for r in rows:
        for s in json.loads(r["missing_skills"] or "[]"):
            counts[s] = counts.get(s, 0) + 1
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]
    return [{"skill": s, "count": c} for s, c in top]
