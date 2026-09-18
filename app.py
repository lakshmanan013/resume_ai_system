import os
import time
import json
import sqlite3
from typing import Any, Optional
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                    session, flash, jsonify, send_from_directory, abort, Response)
from werkzeug.utils import secure_filename

from config import Config
import database
import models
from resume_parser import parse_resume, validate_resume_file, compute_gap_analysis, ScannedResumeError
from skill_matcher import rank_jobs, compute_match
from skills_data import ALL_SKILLS, SKILL_TAXONOMY, ROLE_PROFILES

app = Flask(__name__)
app.config.from_object(Config)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)

database.register_db(app)
database.init_db(app)


# ---------------------------------------------------------------- helpers & auth
def login_required(f):
    @wraps(f)
    def wrapped(*a, **kw):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login", next=request.path))
        return f(*a, **kw)
    return wrapped


def admin_required(f):
    @wraps(f)
    def wrapped(*a, **kw):
        if "user_id" not in session:
            flash("Please log in to continue.", "error")
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            abort(403)
        return f(*a, **kw)
    return wrapped


def current_user():
    if "user_id" not in session:
        return None
    return models.get_user_by_id(session["user_id"])


def check_password_strength(password: str) -> tuple[bool, str]:
    """Validates password strength: min length 8, uppercase, lowercase, and number."""
    if len(password) < app.config.get("PASSWORD_MIN_LENGTH", 8):
        return False, f"Password must be at least {app.config.get('PASSWORD_MIN_LENGTH', 8)} characters long."
    if not any(c.isupper() for c in password):
        return False, "Password must include at least one uppercase letter (A-Z)."
    if not any(c.islower() for c in password):
        return False, "Password must include at least one lowercase letter (a-z)."
    if not any(c.isdigit() for c in password):
        return False, "Password must include at least one numeric digit (0-9)."
    return True, ""


@app.context_processor
def inject_globals():
    return {
        "current_user": current_user(),
        "role_profiles": ROLE_PROFILES,
    }


# ---------------------------------------------------------------- public
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------- auth & password reset
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        errors = []
        if not name:
            errors.append("Name is required.")
        if not email or "@" not in email:
            errors.append("A valid email address is required.")

        strength_ok, strength_msg = check_password_strength(password)
        if not strength_ok:
            errors.append(strength_msg)

        if password != confirm:
            errors.append("Passwords do not match.")
        if email and models.get_user_by_email(email):
            errors.append("An account with this email already exists.")

        if errors:
            for e in errors:
                flash(e, "error")
            return render_template("register.html", name=name, email=email)

        models.create_user(name, email, password)
        flash("Account created successfully. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = models.get_user_by_email(email)

        if not user:
            flash("Invalid email or password.", "error")
            return render_template("login.html", email=email)

        # Rate-limiting brute-force check
        if models.is_account_locked(user):
            flash(
                "Your account is temporarily locked due to multiple failed login attempts. "
                "Please wait 15 minutes or reset your password.",
                "error"
            )
            return render_template("login.html", email=email)

        if not models.verify_password(user, password):
            models.record_login_failure(
                email,
                max_attempts=app.config.get("MAX_LOGIN_ATTEMPTS", 5),
                lockout_minutes=app.config.get("LOCKOUT_MINUTES", 15)
            )
            user_fresh = models.get_user_by_email(email)
            attempts = user_fresh["failed_attempts"] if user_fresh else 1
            max_att = app.config.get("MAX_LOGIN_ATTEMPTS", 5)
            remaining = max(0, max_att - attempts)
            if remaining == 0:
                flash("Account has now been locked for 15 minutes due to too many failed attempts.", "error")
            else:
                flash(f"Invalid email or password. {remaining} attempt(s) remaining before account lockout.", "error")
            return render_template("login.html", email=email)

        if not user["is_active"]:
            flash("This account has been deactivated. Contact an administrator.", "error")
            return render_template("login.html", email=email)

        # Login successful -> reset failure counter
        models.reset_login_failures(user["id"])

        session["user_id"] = user["id"]
        session["role"] = user["role"]
        session["name"] = user["name"]
        flash(f"Welcome back, {user['name']}!", "success")

        next_url = request.args.get("next")
        if user["role"] == "admin":
            return redirect(next_url or url_for("admin_dashboard"))
        return redirect(next_url or url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been safely logged out.", "success")
    return redirect(url_for("index"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Module 1: Password reset via time-limited token."""
    reset_link_dev = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        user = models.get_user_by_email(email)
        if user:
            token = models.generate_reset_token(email)
            reset_link_dev = url_for("reset_password", token=token, _external=True)
            flash(
                f"Password reset token issued! In development, use link below: {reset_link_dev}",
                "info"
            )
        else:
            flash("If an account exists with that email, a password reset link has been dispatched.", "info")
        return render_template("forgot_password.html", email=email, submitted=True, reset_link=reset_link_dev)

    return render_template("forgot_password.html", submitted=False)


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Module 1: Token verification and password update."""
    user = models.verify_reset_token(token, max_age=app.config.get("RESET_TOKEN_MAX_AGE", 3600))
    if not user:
        flash("Password reset link is invalid or has expired. Please request a new link.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        strength_ok, strength_msg = check_password_strength(password)
        if not strength_ok:
            flash(strength_msg, "error")
            return render_template("reset_password.html", token=token)

        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html", token=token)

        models.reset_user_password(user["id"], password)
        flash("Your password has been successfully updated! You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)


@app.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        user = current_user()
        if user is None:
            flash("User session expired. Please log in again.", "error")
            return redirect(url_for("login"))
        if not models.verify_password(user, current):
            flash("Current password is incorrect.", "error")
        else:
            strength_ok, strength_msg = check_password_strength(new)
            if not strength_ok:
                flash(strength_msg, "error")
            elif new != confirm:
                flash("New passwords do not match.", "error")
            else:
                models.set_password(user["id"], new)
                flash("Password updated successfully.", "success")
                return redirect(url_for("dashboard"))
    return render_template("change_password.html")


# ---------------------------------------------------------------- resumes & human-in-the-loop
@app.route("/dashboard")
@login_required
def dashboard():
    resume = models.resume_to_dict(models.get_latest_resume(session["user_id"]))
    history = [models.resume_to_dict(r) for r in models.list_user_resumes(session["user_id"])]
    return render_template("dashboard.html", resume=resume, resume_history=history)


@app.route("/resume/upload", methods=["GET", "POST"])
@login_required
def upload_resume():
    if request.method == "POST":
        file = request.files.get("resume")
        if not file or not file.filename:
            flash("Please select a resume file (PDF or DOCX).", "error")
            return redirect(url_for("upload_resume"))

        raw_filename = file.filename
        safe_name = secure_filename(raw_filename)
        filename = f"user{session['user_id']}_{int(time.time())}_{safe_name}"
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        # Validate MIME type and magic byte signature
        valid, error = validate_resume_file(raw_filename, app.config["ALLOWED_EXTENSIONS"], filepath=filepath)
        if not valid:
            os.remove(filepath)
            flash(error if error is not None else "Invalid file format.", "error")
            return redirect(url_for("upload_resume"))

        # Ingest and extract text, detecting scanned PDFs gracefully
        try:
            parsed = parse_resume(filepath)
        except ScannedResumeError as sre:
            os.remove(filepath)
            flash(str(sre), "error")
            return redirect(url_for("upload_resume"))
        except Exception as e:
            os.remove(filepath)
            flash(f"Could not parse this resume: {e}", "error")
            return redirect(url_for("upload_resume"))

        if not parsed.get("skills"):
            flash(
                "Notice: Very few standardized skills were extracted automatically. "
                "You can add your technical skills on the review screen below.",
                "error"
            )

        resume_id = models.save_resume(session["user_id"], raw_filename, filepath, parsed, is_confirmed=0)
        flash("Resume successfully parsed! Please review and confirm your extracted details below.", "success")
        return redirect(url_for("confirm_resume_view", resume_id=resume_id))

    existing = models.get_latest_resume(session["user_id"])
    return render_template("upload_resume.html", existing=models.resume_to_dict(existing))


@app.route("/resume/<int:resume_id>/confirm", methods=["GET", "POST"])
@login_required
def confirm_resume_view(resume_id):
    """
    Module 2: Human-in-the-loop review.
    Shows extraction results to the user for confirmation and correction before matching.
    """
    resume = models.resume_to_dict(models.get_resume(resume_id))
    if not resume or (resume["user_id"] != session["user_id"] and session.get("role") != "admin"):
        abort(404)

    if request.method == "POST":
        skills_raw = request.form.get("skills", "")
        skills = [s.strip() for s in skills_raw.split(",") if s.strip()]
        exp_years = request.form.get("experience_years", "")
        name = request.form.get("name", "")
        email = request.form.get("email", "")
        phone = request.form.get("phone", "")

        models.update_resume_data(
            resume_id,
            user_id=None if session.get("role") == "admin" else session["user_id"],
            skills=skills,
            experience_years=exp_years,
            name=name,
            email=email,
            phone=phone
        )
        models.confirm_resume(resume_id, user_id=session["user_id"])
        flash("Profile verified and confirmed! Calculating tailored AI job matches...", "success")
        return redirect(url_for("job_recommendations"))

    return render_template("resume_confirm.html", resume=resume)


@app.route("/resume/<int:resume_id>/analysis")
@login_required
def resume_analysis(resume_id):
    """
    Module 3: Resume Analysis with spaCy NER, date range experience,
    and Target Role Gap Analysis.
    """
    resume = models.resume_to_dict(models.get_resume(resume_id))
    if not resume or (resume["user_id"] != session["user_id"] and session.get("role") != "admin"):
        abort(404)

    target_role = request.args.get("target_role", "Full Stack Engineer")
    gap_analysis = compute_gap_analysis(resume.get("skills", []), target_role=target_role)

    return render_template(
        "resume_analysis.html",
        resume=resume,
        target_role=target_role,
        gap_analysis=gap_analysis,
        role_profiles=ROLE_PROFILES
    )


# ---------------------------------------------------------------- matching & job recommendation
@app.route("/jobs")
@login_required
def job_recommendations():
    """
    Module 5: Multi-faceted job recommendations with filtering (location, score,
    job type, seniority) and fuzzy search across title/company/description.
    """
    resume = models.resume_to_dict(models.get_latest_resume(session["user_id"]))
    if not resume:
        flash("Please upload a resume first to receive personalized recommendations.", "error")
        return redirect(url_for("upload_resume"))

    location_filter = request.args.get("location", "").strip()
    job_type_filter = request.args.get("job_type", "").strip()
    seniority_filter = request.args.get("seniority", "").strip()
    search_query = request.args.get("q", "").strip()
    threshold = int(request.args.get("threshold", 0))

    # Fetch jobs matching faceted filters
    raw_filtered = models.list_jobs(
        active_only=True,
        search_query=search_query,
        location=location_filter,
        job_type=job_type_filter,
        seniority=seniority_filter
    )
    filtered_jobs: list[dict[str, Any]] = [
        d for j in raw_filtered if (d := models.job_to_dict(j)) is not None
    ]

    all_ranked = rank_jobs(
        candidate_skills=resume["skills"],
        jobs=filtered_jobs,
        candidate_experience_years=resume.get("experience_years"),
        threshold=threshold,
        resume_raw_text=resume.get("raw_text")
    )

    if all_ranked:
        models.bulk_save_matches(session["user_id"], resume["id"], all_ranked)

    all_active: list[dict[str, Any]] = [
        d for j in models.list_jobs(active_only=True) if (d := models.job_to_dict(j)) is not None
    ]
    locations = sorted({str(j["location"]) for j in all_active if j.get("location")})
    job_types = ["Full-Time", "Remote", "Hybrid", "Onsite"]
    seniority_levels = ["Entry-Level", "Mid-Level", "Senior", "Lead"]

    return render_template(
        "job_recommendations.html",
        jobs=all_ranked,
        resume=resume,
        threshold=threshold,
        locations=locations,
        job_types=job_types,
        seniority_levels=seniority_levels,
        location_filter=location_filter,
        job_type_filter=job_type_filter,
        seniority_filter=seniority_filter,
        search_query=search_query
    )


@app.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id):
    """
    Job detail view with matched vs missing skill highlights and score explanation.
    """
    job = models.job_to_dict(models.get_job(job_id))
    if not job:
        abort(404)
    resume = models.resume_to_dict(models.get_latest_resume(session["user_id"]))
    match = None
    if resume:
        match = compute_match(
            candidate_skills=resume["skills"],
            job_required_skills=job["required_skills"],
            job_preferred_skills=job["preferred_skills"],
            candidate_experience_years=resume.get("experience_years"),
            job_min_experience=job.get("min_experience"),
            resume_raw_text=resume.get("raw_text"),
            job_description=job.get("description"),
            job_id=job["id"]
        )
    return render_template("job_detail.html", job=job, match=match)


# ---------------------------------------------------------------- admin module (Module 6)
@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = models.get_stats()
    return render_template("admin/dashboard.html", stats=stats)


@app.route("/admin/users")
@admin_required
def admin_users():
    search = request.args.get("q", "").strip()
    return render_template("admin/users.html", users=models.list_users(search_term=search), search_query=search)


@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_user(user_id):
    user = models.get_user_by_id(user_id)
    if not user:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "user")
        if not name or not email:
            flash("Name and email are required.", "error")
            return render_template("admin/edit_user.html", user=user)
        try:
            models.update_user(user_id, name, email, role)
            flash("User updated successfully.", "success")
            return redirect(url_for("admin_users"))
        except sqlite3.IntegrityError:
            flash("An account with this email already exists.", "error")
            return render_template("admin/edit_user.html", user=dict(user, name=name, email=email, role=role))
    return render_template("admin/edit_user.html", user=user)


@app.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_user(user_id):
    user = models.get_user_by_id(user_id)
    if not user:
        abort(404)
    if user_id == session["user_id"]:
        flash("You cannot deactivate your own administrative account.", "error")
    else:
        models.set_user_active(user_id, not user["is_active"])
        flash("User status successfully updated.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/resumes")
@admin_required
def admin_resumes():
    search = request.args.get("q", "").strip()
    resumes = [models.resume_to_dict(r) for r in models.list_all_resumes(search_term=search)]
    return render_template("admin/resumes.html", resumes=resumes, search_query=search)


@app.route("/admin/resumes/<int:resume_id>/download")
@admin_required
def admin_download_resume(resume_id):
    resume = models.get_resume(resume_id)
    if not resume:
        abort(404)
    directory, filename = os.path.split(resume["filepath"])
    return send_from_directory(directory, filename, as_attachment=True,
                                download_name=resume["filename"])


@app.route("/admin/jobs")
@admin_required
def admin_jobs():
    search = request.args.get("q", "").strip()
    return render_template(
        "admin/jobs.html",
        jobs=[models.job_to_dict(j) for j in models.list_jobs(active_only=False, search_query=search)],
        search_query=search,
        adzuna_configured=Config.is_adzuna_configured(),
        last_synced=models.get_last_adzuna_sync_time()
    )


@app.route("/admin/jobs/sync", methods=["POST"])
@app.route("/api/admin/jobs/sync", methods=["POST"])
@admin_required
def admin_sync_jobs():
    """Triggers synchronous live sync with Adzuna API (with fallback to live feeds if unconfigured)."""
    import adzuna_client
    if not Config.is_adzuna_configured():
        try:
            res = models.sync_live_jobs()
            msg = f"Live jobs refreshed ({res.get('added', 0)} added). To sync from Adzuna, configure ADZUNA_APP_ID and ADZUNA_APP_KEY."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json or "/api/" in request.path:
                return jsonify({"success": True, "message": msg, "synced": res.get("added", 0)})
            flash(msg, "info")
            return redirect(url_for("admin_jobs"))
        except Exception:
            err_msg = "Adzuna live sync is not configured. Please set ADZUNA_APP_ID and ADZUNA_APP_KEY."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json or "/api/" in request.path:
                return jsonify({"success": False, "error": err_msg}), 400
            flash(err_msg, "error")
            return redirect(url_for("admin_jobs"))

    try:
        result = adzuna_client.sync_jobs()
        if result.get("success"):
            msg = result.get("message") or f"Successfully synced {result.get('synced', 0)} jobs from Adzuna."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json or "/api/" in request.path:
                return jsonify({"success": True, "message": msg, "synced": result.get("synced", 0)})
            flash(msg, "success")
        else:
            err_msg = result.get("message") or "Sync failed with Adzuna API."
            if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json or "/api/" in request.path:
                return jsonify({"success": False, "error": err_msg}), 500
            flash(err_msg, "error")
    except Exception as e:
        err_msg = f"Adzuna sync error: {str(e)}"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.is_json or "/api/" in request.path:
            return jsonify({"success": False, "error": err_msg}), 500
        flash(err_msg, "error")

    return redirect(url_for("admin_jobs"))


@app.route("/admin/jobs/new", methods=["GET", "POST"])
@admin_required
def admin_new_job():
    if request.method == "POST":
        _save_job_form()
        flash("New job listing created successfully.", "success")
        return redirect(url_for("admin_jobs"))
    return render_template("admin/job_form.html", job=None)


@app.route("/admin/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_job(job_id):
    job = models.job_to_dict(models.get_job(job_id))
    if not job:
        abort(404)
    if job.get("source", "").lower() == "adzuna":
        flash("Adzuna-synced jobs are read-only and cannot be manually edited.", "error")
        return redirect(url_for("admin_jobs"))
    if request.method == "POST":
        _save_job_form(job_id)
        flash("Job listing updated successfully.", "success")
        return redirect(url_for("admin_jobs"))
    return render_template("admin/job_form.html", job=job)


def _save_job_form(job_id=None):
    title = request.form["title"].strip()
    company = request.form["company"].strip()
    location = request.form["location"].strip()
    description = request.form["description"].strip()
    required = [s.strip().lower() for s in request.form["required_skills"].split(",") if s.strip()]
    preferred = [s.strip().lower() for s in request.form.get("preferred_skills", "").split(",") if s.strip()]
    min_exp = float(request.form.get("min_experience") or 0)
    job_type = request.form.get("job_type", "Full-Time").strip()
    seniority = request.form.get("seniority_level", "Mid-Level").strip()
    openings_count = int(request.form.get("openings_count") or 1)
    source = request.form.get("source", "manual").strip()

    if job_id:
        models.update_job(job_id, title, company, location, description, required, preferred, min_exp,
                          job_type=job_type, seniority_level=seniority, openings_count=openings_count, source=source)
    else:
        models.create_job(title, company, location, description, required, preferred, min_exp,
                          job_type=job_type, seniority_level=seniority, openings_count=openings_count, source=source)


@app.route("/admin/jobs/<int:job_id>/delete", methods=["POST"])
@admin_required
def admin_delete_job(job_id):
    models.delete_job(job_id)
    flash("Job listing deleted.", "success")
    return redirect(url_for("admin_jobs"))


@app.route("/admin/jobs/<int:job_id>/toggle", methods=["POST"])
@admin_required
def admin_toggle_job(job_id):
    job = models.get_job(job_id)
    if not job:
        abort(404)
    models.set_job_active(job_id, not job["is_active"])
    flash("Job status updated.", "success")
    return redirect(url_for("admin_jobs"))



@app.route("/admin/matches")
@admin_required
def admin_matches():
    search = request.args.get("q", "").strip()
    matches = models.list_all_matches(search_term=search)
    return render_template("admin/matches.html", matches=matches, search_query=search)


@app.route("/admin/reports")
@admin_required
def admin_reports():
    stats = models.get_stats()
    return render_template("admin/reports.html", stats=stats)


@app.route("/admin/reports/export.json")
@admin_required
def admin_export_report_json():
    return jsonify(models.get_stats())


@app.route("/admin/reports/export.csv")
@admin_required
def admin_export_report_csv():
    csv_data = models.export_stats_csv()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=resume_ai_market_analytics.csv"}
    )


# ---------------------------------------------------------------- dynamic APIs
@app.route("/api/skills/suggestions")
def api_skill_suggestions():
    q = request.args.get("q", "").strip().lower()
    if q:
        matched = [s for s in ALL_SKILLS if q in s][:15]
    else:
        matched = ALL_SKILLS[:30]
    return jsonify({"skills": matched, "taxonomy": SKILL_TAXONOMY})


@app.route("/api/resume/<int:resume_id>/update", methods=["POST"])
@login_required
def api_update_resume(resume_id):
    resume = models.resume_to_dict(models.get_resume(resume_id))
    if not resume or (resume["user_id"] != session["user_id"] and session.get("role") != "admin"):
        return jsonify({"error": "Resume not found or unauthorized"}), 404

    data = request.get_json(silent=True) or {}
    skills = data.get("skills")
    experience_years = data.get("experience_years")
    name = data.get("parsed_name")
    email = data.get("email")
    phone = data.get("phone")

    updated = models.update_resume_data(
        resume_id,
        user_id=None if session.get("role") == "admin" else session["user_id"],
        skills=skills,
        experience_years=experience_years,
        name=name,
        email=email,
        phone=phone
    )

    if not updated:
        return jsonify({"error": "Failed to update resume"}), 400

    # Re-rank jobs dynamically with hybrid scoring
    jobs: list[dict[str, Any]] = [
        d for j in models.list_jobs(active_only=True) if (d := models.job_to_dict(j)) is not None
    ]
    ranked = rank_jobs(
        updated["skills"], jobs, updated["experience_years"],
        threshold=0, resume_raw_text=updated.get("raw_text")
    )
    if ranked:
        models.bulk_save_matches(updated["user_id"], updated["id"], ranked)

    return jsonify({
        "success": True,
        "resume": updated,
        "ranked_jobs": ranked,
        "message": "Resume updated and job matches recalculated!"
    })


@app.route("/api/resume/<int:resume_id>/simulate-skill", methods=["POST"])
@login_required
def api_simulate_skill(resume_id):
    resume = models.resume_to_dict(models.get_resume(resume_id))
    if not resume or (resume["user_id"] != session["user_id"] and session.get("role") != "admin"):
        return jsonify({"error": "Resume not found or unauthorized"}), 404

    data = request.get_json(silent=True) or {}
    extra_skills = data.get("extra_skills", [])
    combined_skills = list(set(resume["skills"] + [s.strip().lower() for s in extra_skills if s and s.strip()]))
    job_id = data.get("job_id")

    if job_id:
        job = models.job_to_dict(models.get_job(job_id))
        if not job:
            return jsonify({"error": "Job not found"}), 404
        original_match = compute_match(
            resume["skills"], job["required_skills"], job["preferred_skills"],
            resume["experience_years"], job["min_experience"],
            resume_raw_text=resume.get("raw_text"), job_description=job.get("description"), job_id=job_id
        )
        simulated_match = compute_match(
            combined_skills, job["required_skills"], job["preferred_skills"],
            resume["experience_years"], job["min_experience"],
            resume_raw_text=resume.get("raw_text"), job_description=job.get("description"), job_id=job_id
        )
        return jsonify({
            "success": True,
            "job_id": job_id,
            "original_match": original_match,
            "simulated_match": simulated_match,
            "diff": round(simulated_match["score"] - original_match["score"], 1)
        })

    jobs: list[dict[str, Any]] = [
        d for j in models.list_jobs(active_only=True) if (d := models.job_to_dict(j)) is not None
    ]
    simulated_ranked = rank_jobs(
        combined_skills, jobs, resume["experience_years"],
        threshold=0, resume_raw_text=resume.get("raw_text")
    )
    return jsonify({
        "success": True,
        "simulated_ranked": simulated_ranked
    })


@app.route("/api/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def api_admin_toggle_user(user_id):
    user = models.get_user_by_id(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404
    if user_id == session["user_id"]:
        return jsonify({"error": "You cannot deactivate your own account"}), 400

    new_status = not bool(user["is_active"])
    models.set_user_active(user_id, new_status)
    return jsonify({
        "success": True,
        "user_id": user_id,
        "is_active": new_status,
        "message": f"User '{user['name']}' is now {'active' if new_status else 'inactive'}."
    })


@app.route("/api/admin/jobs/<int:job_id>/toggle", methods=["POST"])
@admin_required
def api_admin_toggle_job(job_id):
    job = models.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    new_status = not bool(job["is_active"])
    models.set_job_active(job_id, new_status)
    return jsonify({
        "success": True,
        "job_id": job_id,
        "is_active": new_status,
        "message": f"Job listing '{job['title']}' is now {'active' if new_status else 'hidden'}."
    })


@app.route("/api/admin/jobs/<int:job_id>/delete", methods=["POST", "DELETE"])
@admin_required
def api_admin_delete_job(job_id):
    job = models.get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404

    models.delete_job(job_id)
    return jsonify({
        "success": True,
        "job_id": job_id,
        "message": f"Job listing '{job['title']}' was deleted."
    })


@app.route("/api/admin/stats")
@admin_required
def api_admin_stats():
    return jsonify(models.get_stats())


@app.route("/api/jobs/live-feed")
def api_jobs_live_feed():
    """
    Returns real-time status and latest live jobs synced from Adzuna (updated every 10s).
    If user is authenticated with a resume, returns match-ranked recommendations.
    """
    import auto_job_syncer
    status = auto_job_syncer.get_auto_syncer_status()
    total_active = models.get_active_jobs_count()
    latest_jobs = models.get_latest_active_jobs(limit=15)

    ranked_jobs = []
    user_id = session.get("user_id")
    if user_id:
        resume = models.resume_to_dict(models.get_latest_resume(user_id))
        if resume and resume.get("skills"):
            threshold = int(request.args.get("threshold", 0))
            ranked_jobs = rank_jobs(
                candidate_skills=resume["skills"],
                jobs=latest_jobs,
                candidate_experience_years=resume.get("experience_years"),
                threshold=threshold,
                resume_raw_text=resume.get("raw_text")
            )

    return jsonify({
        "success": True,
        "is_running": status["is_running"],
        "interval_seconds": status["interval_seconds"],
        "last_sync_time": status["last_sync_time"],
        "new_jobs_last_tick": status["new_jobs_last_tick"],
        "total_active_jobs": total_active,
        "latest_jobs": latest_jobs,
        "ranked_jobs": ranked_jobs
    })


@app.route("/api/jobs/sync-status")
def api_jobs_sync_status():
    """Returns operational status of the 10-second automatic Adzuna job syncer."""
    import auto_job_syncer
    return jsonify(auto_job_syncer.get_auto_syncer_status())


@app.route("/api/jobs/sync-now", methods=["POST"])
def api_jobs_sync_now():
    """Triggers an immediate live sync cycle from Adzuna into the database."""
    import auto_job_syncer
    result = auto_job_syncer.trigger_manual_sync()
    return jsonify({
        "success": result.get("success", False),
        "result": result,
        "status": auto_job_syncer.get_auto_syncer_status()
    })


@app.route("/api/jobs/<int:job_id>/apply", methods=["POST"])
@login_required
def api_apply_job(job_id):
    job = models.get_job(job_id)
    if not job:
        return jsonify({"error": "Job listing not found"}), 404
    return jsonify({
        "success": True,
        "job_id": job_id,
        "job_title": job["title"],
        "company": job["company"],
        "message": f"Application successfully submitted to {job['company']} for '{job['title']}'!"
    })


# ---------------------------------------------------------------- errors
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="You don't have permission to view this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404


# ---------------------------------------------------------------- background 10s auto-syncer startup
import auto_job_syncer

if Config.is_adzuna_configured():
    # Only start once if running with reloader
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        auto_job_syncer.start_auto_syncer(interval_seconds=10)
    else:
        auto_job_syncer.start_auto_syncer(interval_seconds=10)


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=True)

