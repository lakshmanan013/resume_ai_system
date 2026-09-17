import os
import time
import json
import sqlite3
from functools import wraps
from flask import (Flask, render_template, request, redirect, url_for,
                    session, flash, jsonify, send_from_directory, abort)
from werkzeug.utils import secure_filename

from config import Config
import database
import models
from resume_parser import parse_resume, validate_resume_file
from skill_matcher import rank_jobs, compute_match
from skills_data import ALL_SKILLS, SKILL_TAXONOMY

app = Flask(__name__)
app.config.from_object(Config)
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)

database.register_db(app)
database.init_db(app)


# ---------------------------------------------------------------- helpers
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


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# ---------------------------------------------------------------- public
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------- auth
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
            errors.append("A valid email is required.")
        if len(password) < 8:
            errors.append("Password must be at least 8 characters long.")
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

        if not user or not models.verify_password(user, password):
            flash("Invalid email or password.", "error")
            return render_template("login.html", email=email)
        if not user["is_active"]:
            flash("This account has been deactivated. Contact an administrator.", "error")
            return render_template("login.html", email=email)

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
    flash("You have been logged out.", "success")
    return redirect(url_for("index"))


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
        elif len(new) < 8:
            flash("New password must be at least 8 characters long.", "error")
        elif new != confirm:
            flash("New passwords do not match.", "error")
        else:
            models.set_password(user["id"], new)
            flash("Password updated successfully.", "success")
            return redirect(url_for("dashboard"))
    return render_template("change_password.html")


# ---------------------------------------------------------------- resumes
@app.route("/dashboard")
@login_required
def dashboard():
    resume = models.resume_to_dict(models.get_latest_resume(session["user_id"]))
    return render_template("dashboard.html", resume=resume)


@app.route("/resume/upload", methods=["GET", "POST"])
@login_required
def upload_resume():
    if request.method == "POST":
        file = request.files.get("resume")
        if not file or not file.filename:
            flash("Please choose a resume file to upload.", "error")
            return redirect(url_for("upload_resume"))

        raw_filename: str = file.filename
        valid, error = validate_resume_file(raw_filename, app.config["ALLOWED_EXTENSIONS"])
        if not valid:
            flash(error if error is not None else "Invalid file format.", "error")
            return redirect(url_for("upload_resume"))

        safe_name = secure_filename(raw_filename)
        filename = f"user{session['user_id']}_{int(time.time())}_{safe_name}"
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        try:
            parsed = parse_resume(filepath)
        except Exception as e:
            os.remove(filepath)
            flash(f"Could not process this resume: {e}", "error")
            return redirect(url_for("upload_resume"))

        if not parsed["skills"]:
            flash("Warning: no recognizable skills were found in this resume. "
                  "You can still proceed, but job matching may be inaccurate.", "error")

        resume_id = models.save_resume(session["user_id"], raw_filename, filepath, parsed)
        flash("Resume uploaded and analyzed successfully!", "success")
        return redirect(url_for("resume_analysis", resume_id=resume_id))

    existing = models.get_latest_resume(session["user_id"])
    return render_template("upload_resume.html", existing=models.resume_to_dict(existing))


@app.route("/resume/<int:resume_id>/analysis")
@login_required
def resume_analysis(resume_id):
    resume = models.resume_to_dict(models.get_resume(resume_id))
    if not resume or (resume["user_id"] != session["user_id"] and session.get("role") != "admin"):
        abort(404)
    return render_template("resume_analysis.html", resume=resume)


# ---------------------------------------------------------------- matching / recommendations
@app.route("/jobs")
@login_required
def job_recommendations():
    resume = models.resume_to_dict(models.get_latest_resume(session["user_id"]))
    if not resume:
        flash("Upload a resume first to get job recommendations.", "error")
        return redirect(url_for("upload_resume"))

    location_filter = request.args.get("location", "").strip().lower()
    threshold = int(request.args.get("threshold", 0))

    active_job_dicts: list[dict] = [j for j in (models.job_to_dict(job) for job in models.list_jobs(active_only=True)) if j is not None]
    all_ranked = rank_jobs(resume["skills"], active_job_dicts, resume["experience_years"], threshold=0)

    if all_ranked:
        models.bulk_save_matches(session["user_id"], resume["id"], all_ranked)

    locations = sorted({str(j["location"]) for j in active_job_dicts if j.get("location")})
    return render_template("job_recommendations.html", jobs=all_ranked, resume=resume,
                            threshold=threshold, locations=locations,
                            location_filter=location_filter)


@app.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id):
    job = models.job_to_dict(models.get_job(job_id))
    if not job:
        abort(404)
    resume = models.resume_to_dict(models.get_latest_resume(session["user_id"]))
    match = None
    if resume:
        match = compute_match(resume["skills"], job["required_skills"], job["preferred_skills"],
                               resume["experience_years"], job["min_experience"])
    return render_template("job_detail.html", job=job, match=match)


# ---------------------------------------------------------------- admin
@app.route("/admin")
@admin_required
def admin_dashboard():
    stats = models.get_stats()
    return render_template("admin/dashboard.html", stats=stats)


@app.route("/admin/users")
@admin_required
def admin_users():
    return render_template("admin/users.html", users=models.list_users())


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
            flash("User updated.", "success")
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
        flash("You cannot deactivate your own account.", "error")
    else:
        models.set_user_active(user_id, not user["is_active"])
        flash("User status updated.", "success")
    return redirect(url_for("admin_users"))


@app.route("/admin/resumes")
@admin_required
def admin_resumes():
    resumes = [models.resume_to_dict(r) for r in models.list_all_resumes()]
    return render_template("admin/resumes.html", resumes=resumes)


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
    return render_template("admin/jobs.html", jobs=[models.job_to_dict(j) for j in models.list_jobs(active_only=False)])


@app.route("/admin/jobs/new", methods=["GET", "POST"])
@admin_required
def admin_new_job():
    if request.method == "POST":
        _save_job_form()
        flash("Job listing created.", "success")
        return redirect(url_for("admin_jobs"))
    return render_template("admin/job_form.html", job=None)


@app.route("/admin/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_job(job_id):
    job = models.job_to_dict(models.get_job(job_id))
    if not job:
        abort(404)
    if request.method == "POST":
        _save_job_form(job_id)
        flash("Job listing updated.", "success")
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
    openings_count = int(request.form.get("openings_count") or 1)
    source = request.form.get("source", "Direct Portal").strip()

    if job_id:
        models.update_job(job_id, title, company, location, description, required, preferred, min_exp,
                          job_type=job_type, openings_count=openings_count, source=source)
    else:
        models.create_job(title, company, location, description, required, preferred, min_exp,
                          job_type=job_type, openings_count=openings_count, source=source)


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
    matches = models.list_all_matches()
    return render_template("admin/matches.html", matches=matches)


@app.route("/admin/reports")
@admin_required
def admin_reports():
    stats = models.get_stats()
    return render_template("admin/reports.html", stats=stats)


@app.route("/admin/reports/export.json")
@admin_required
def admin_export_report():
    return jsonify(models.get_stats())


# ---------------------------------------------------------------- dynamic apis
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

    # Re-rank jobs dynamically
    jobs = [models.job_to_dict(j) for j in models.list_jobs(active_only=True)]
    ranked = rank_jobs(updated["skills"], jobs, updated["experience_years"], threshold=0)
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
            resume["experience_years"], job["min_experience"]
        )
        simulated_match = compute_match(
            combined_skills, job["required_skills"], job["preferred_skills"],
            resume["experience_years"], job["min_experience"]
        )
        return jsonify({
            "success": True,
            "job_id": job_id,
            "original_match": original_match,
            "simulated_match": simulated_match,
            "diff": round(simulated_match["score"] - original_match["score"], 1)
        })

    jobs = [models.job_to_dict(j) for j in models.list_jobs(active_only=True)]
    simulated_ranked = rank_jobs(combined_skills, jobs, resume["experience_years"], threshold=0)
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


@app.route("/api/admin/jobs/sync", methods=["POST"])
@admin_required
def api_admin_sync_jobs():
    res = models.sync_live_jobs()
    return jsonify({
        "success": True,
        "added": res["added"],
        "total_active": res["total_active"],
        "message": f"Real-time sync complete! {res['total_active']} active roles ready for matching."
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
        "message": f"Application successfully sent to {job['company']} for '{job['title']}'!"
    })



# ---------------------------------------------------------------- errors
@app.errorhandler(403)
def forbidden(e):
    return render_template("error.html", code=403, message="You don't have permission to view this page."), 403


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404, message="Page not found."), 404


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
