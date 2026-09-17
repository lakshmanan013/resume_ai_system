# Resume AI — Resume Analysis & Job Recommendation System

A full-stack web application that parses uploaded resumes, extracts skills and
experience using an NLP/keyword-matching engine, and recommends jobs ranked by
a computed skill-match score.

**Stack:** Python + Flask (backend/AI logic), SQLite (storage), HTML/CSS/JavaScript (frontend, server-rendered with Jinja2).

---

## 1. Features

### User Module
- Registration, login/logout, session-based auth
- Passwords hashed with Werkzeug's `generate_password_hash` (never stored in plain text)
- "Change password" flow with current-password verification

### Resume Upload Module
- Upload PDF or DOCX (10 MB max), with client- and server-side validation
- Automatic extraction of: name, email, phone, education lines, skills, years of experience
- Resumes stored in SQLite with the raw parsed text kept for re-analysis
- Re-upload replaces the active resume used for matching

### Resume Analysis Module
- Dedicated analysis page showing everything extracted from the resume
- Flags when no skills / education could be confidently detected

### AI Skill Matching Module (`skill_matcher.py`)
- Compares candidate skills against each job's **required** and **preferred** skill lists
- Weighted score: 80% required-skill coverage + 20% preferred-skill coverage
- Applies an experience-fit penalty if the candidate's detected experience is below
  a job's minimum
- Returns matched skills, missing skills, and extra skills per job

### Job Recommendation Module
- Ranks all active job listings by match score
- Filter by location and by a minimum match-score threshold (slider)
- Job detail page shows exactly which required/preferred skills are met vs. missing

### Admin Module
- Manage users: view, edit (name/email/role), activate/deactivate
- Manage job listings: create / edit / delete / hide
- View all uploaded resumes (with download)
- View a log of all matching activity across all users
- Reports: usage stats, average match score, most-matched jobs, most commonly
  missing skills (useful for identifying upskilling opportunities), JSON export

---

## 2. How the "AI" works

The matching engine is a transparent, explainable pipeline rather than a
black-box model, which keeps the project dependency-free and fast:

1. **Extraction** (`resume_parser.py`): resume text is pulled from PDF (via
   `pdfplumber`) or DOCX (via `python-docx`), then regex + keyword heuristics
   pull out contact info, education lines, and years of experience.
2. **Skill tagging** (`skills_data.py` + `resume_parser.py`): resume text is
   scanned against a curated ~150-term skill taxonomy (languages, frameworks,
   cloud/DevOps, data/AI, soft skills, etc.) using word-boundary regex matching
   so short terms like "r" or "c" don't false-positive.
3. **Scoring** (`skill_matcher.py`): candidate skills are set-intersected
   against each job's required/preferred skill sets to produce a percentage
   match score, with the missing-skill list surfaced directly to the user.

This design can be swapped later for an embeddings/LLM-based matcher without
touching the rest of the app — `skill_matcher.compute_match()` is the single
integration point.

---

## 3. Project structure

```
resume_ai_system/
├── app.py                 # Flask routes (all 6 modules)
├── config.py               # App configuration
├── database.py              # Schema + seeding (sample jobs, default admin)
├── models.py                 # Data access layer
├── resume_parser.py           # PDF/DOCX text extraction + field parsing
├── skill_matcher.py            # Scoring engine
├── skills_data.py                # Skill taxonomy
├── requirements.txt
├── static/
│   ├── css/style.css        # Hand-written CSS (no framework dependency)
│   └── js/main.js            # Upload UX, confirm dialogs, flash auto-dismiss
├── templates/                 # Jinja2 templates (base + admin layout)
└── uploads/                    # Uploaded resume files (created at runtime)
```

---

## 4. Setup & run

```bash
cd resume_ai_system
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

python app.py
```

The app runs at **http://127.0.0.1:5000**. The database (`instance/resume_ai.db`)
and 10 sample job listings are created automatically on first run.

### Default admin login
```
email:    admin@resumeai.local
password: Admin@123
```
Change this password immediately in a real deployment (`config.py` → set a
real `SECRET_KEY` too, via the `SECRET_KEY` environment variable).

---

## 5. Notes & next steps for production

- Swap the dev server for a WSGI server (gunicorn/uwsgi) behind nginx.
- Swap SQLite for PostgreSQL for concurrent multi-user load.
- Add rate limiting / CSRF tokens (Flask-WTF) on forms.
- Add email verification and a real password-reset flow (currently
  "change password" requires being logged in; a token-based "forgot password"
  email flow would be the next addition).
- The skill taxonomy in `skills_data.py` is easily extended — add terms to the
  relevant category list and both extraction and matching pick them up automatically.
