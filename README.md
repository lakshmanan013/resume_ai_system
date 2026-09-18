# Resume AI — AI/ML-Powered Resume Analyzer & Job Recommendation System

**Resume AI** is an end-to-end, production-grade web application that leverages Natural Language Processing (spaCy NER) and Semantic Embeddings (`sentence-transformers` with scikit-learn TF-IDF fallback) to parse resumes, normalize skills, analyze experience, and match candidates to active job openings with explainable AI scoring.

---

## Architecture & Tech Stack

| Layer | Technologies | Details |
| :--- | :--- | :--- |
| **Frontend** | HTML5, CSS3, Vanilla JavaScript | Responsive design, glassmorphism UI, interactive score simulators, dynamic autocomplete |
| **Backend** | Python 3.11+, Flask | RESTful endpoints, Jinja2 templating, modular service layer |
| **Database** | MySQL (Database: `ai_resume`) / SQLite (Fallback) | Real-time persistence, indexed fields, PyMySQL connection pooling & wrapper |
| **Parsing** | `pdfplumber`, `python-docx` | Magic byte MIME validation, scanned/image PDF detection (`ScannedResumeError`) |
| **NLP & NER** | spaCy (`en_core_web_sm`), `EntityRuler` | Name/Org/Date extraction, entity rule-based skill capture, date-range experience calculation |
| **AI / ML Matching** | `sentence-transformers`, `scikit-learn` | Dual-engine: `all-MiniLM-L6-v2` embeddings with cosine similarity + TF-IDF fallback |
| **Security & Auth**| Werkzeug, `itsdangerous` | PBKDF2 password hashing, brute-force rate-limiting, time-limited cryptographic reset tokens |

---

## Comprehensive Module Breakdown

### Module 1 — User Registration & Authentication
- **Secure Password Hashing:** Werkzeug PBKDF2 hashing with salt (passwords never stored in plaintext).
- **Password Strength Rules:** Minimum 8 characters, enforcing uppercase, lowercase, and numeric digits.
- **Brute-Force Rate Limiting:** Locks accounts after 5 failed login attempts for 15 minutes (with remaining lockout countdown displayed).
- **Cryptographic Password Reset:** Uses `itsdangerous.URLSafeTimedSerializer` with a 1-hour expiration token (`/forgot-password` & `/reset-password/<token>`).

### Module 2 — Resume Ingestion & Human-in-the-Loop Validation
- **Strict File Validation:** Restricts uploads to PDF and DOCX under 10MB; validates magic bytes (`%PDF-` and `PK\x03\x04`) rather than trusting file extensions alone.
- **Scanned PDF Rejection:** Detects scanned or image-only PDFs with near-zero extractable text, raising `ScannedResumeError` with an actionable prompt.
- **Structured Field Extraction:** Pulls candidate name, email, phone, education entries, normalized skills, and total years of experience.
- **Versioned Resumes:** Users can re-upload resumes without losing historical records.
- **Human-in-the-Loop Review:** Directs users to `/resume/<id>/confirm` after upload, allowing candidates to review and correct extracted fields before matching algorithms run.

### Module 3 — NLP & Semantic Resume Analysis
- **spaCy NER Pipeline:** Extracts candidate name (`PERSON`), institutions (`ORG`), and temporal dates (`DATE`).
- **Custom `EntityRuler`:** Discovers emerging tech skills, toolchains, and phrases beyond rigid keyword lists.
- **Canonical Skill Normalization:** Maps synonyms and abbreviations to industry standards (e.g., `JS` $\rightarrow$ `JavaScript`, `ReactJS` $\rightarrow$ `React`, `k8s` $\rightarrow$ `Kubernetes`, `TF` $\rightarrow$ `TensorFlow`).
- **Date-Range Experience Calculation:** Computes cumulative professional tenure by parsing date intervals (e.g., `2020 - Present`, `06/2018 - 12/2021`) rather than relying on crude regex patterns.
- **Target Role Gap Analysis:** Evaluates candidate skills against standard role benchmarks (Frontend, Backend, Full Stack, Data Scientist, DevOps, ML Engineer) with completion meters and prioritized missing skills.

### Module 4 — Dual-Engine AI Skill Matching
The core matching engine implements a dual-layer strategy:

1. **Semantic Embeddings (`sentence-transformers/all-MiniLM-L6-v2`):**
   - Embeds candidate skills and job requirements into 384-dimensional dense vectors.
   - Computes cosine similarity to capture semantic equivalence (e.g., *"backend JavaScript"* semantically matches *"Node.js"*).
   - In-memory caching (`_EMBEDDING_CACHE`) avoids redundant tensor operations on unchanging job postings.
2. **TF-IDF + Cosine Similarity Fallback:**
   - Automatically activates if the neural embedding model fails or if PyTorch is unavailable.
3. **Transparent & Explainable Scoring Formula:**
   $$\text{Final Score} = (0.60 \times S_{\text{semantic}}) + (0.30 \times S_{\text{coverage}}) + (0.10 \times S_{\text{experience}})$$
   - **Semantic Skill Similarity (60%):** Vector cosine similarity between skill profiles.
   - **Exact Required Skill Coverage (30%):** Percentage of job-required skills held by the candidate.
   - **Experience Fit (10%):** Binary bonus/penalty based on whether candidate meets minimum required experience.
   - *Configurable in `config.py` via `WEIGHT_SEMANTIC`, `WEIGHT_REQUIRED_COVERAGE`, and `WEIGHT_EXPERIENCE`.*
4. **Natural-Language Score Explanations:**
   - Synthesizes personalized narratives (e.g., *"Strong match on backend skills; missing cloud/AWS experience; exceeds experience requirement"*).

### Module 5 — Job Recommendation & Exploration
- **Ranked Recommendations:** Displays job postings ordered by AI match score.
- **Multi-Faceted Filtering:** Real-time client and server filtering by:
  - Location (dropdown / fuzzy match)
  - Minimum Match Score slider (0% to 100%)
  - Work Mode (Remote, Hybrid, Onsite)
  - Seniority Level (Junior, Mid-Level, Senior, Lead, Executive)
- **Fuzzy Search:** Instant keyword search across title, company, and description.
- **Interactive "What-If" Skill Simulator:** Allows candidates to test how acquiring a missing skill (e.g., Docker, AWS) would increase their match score.
- **1-Click Quick Apply:** Fast-track job application pipeline storing candidate applications.

### Module 6 — Administrative Oversight & Market Analytics
- **User Governance:** Search and filter users, toggle active status, adjust roles (User vs. Admin), view resume history.
- **Structured Job CRUD:** Manage job postings with structured required and preferred skills arrays and seniority tiers.
- **Raw Parsed JSON Inspector:** Diagnostic modal in `/admin/resumes` to inspect raw parsed JSON output for extraction troubleshooting.
- **Market Skill Gap Analytics:** Aggregates most in-demand employer skills vs. most common candidate skills to highlight market shortages.
- **Talent Pipeline Alerts:** Identifies top-matched positions and flags active jobs with zero qualified applicants.
- **Exporting:** One-click CSV and JSON exports of hiring analytics (`/admin/reports/export.csv`).

---

## Directory Structure

```
resume_ai_system/
├── app.py                      # Flask routing, auth endpoints, API handlers
├── config.py                   # Application configuration, scoring weights & model settings
├── database.py                 # SQLite initialization, migrations & sample seeding
├── models.py                   # Data access layer (User, Resume, Job, Match, Analytics)
├── resume_parser.py            # PDF/DOCX magic byte parsing, spaCy NER & date processing
├── skill_matcher.py            # Dual-engine scoring (SentenceTransformers + TF-IDF fallback)
├── skills_data.py              # Skill taxonomy, canonical normalization & role benchmarks
├── requirements.txt            # Pinned dependency manifest
├── schema_postgres.sql         # Production PostgreSQL schema with JSONB and indexes
├── static/
│   ├── css/style.css           # Vanilla CSS design system, dark mode & components
│   └── js/main.js              # Dynamic filtering, what-if simulator & admin modals
├── templates/                  # Jinja2 templates (Auth, Resumes, Jobs, Admin Portal)
│   ├── admin/                  # Admin user management, job CRUD, reports & inspector
│   ├── forgot_password.html    # Password reset request form
│   ├── reset_password.html     # Token-validated password reset form
│   ├── resume_confirm.html     # Human-in-the-loop review interface
│   ├── resume_analysis.html    # Target role gap analysis & extraction breakdown
│   ├── job_recommendations.html# Multi-faceted recommendation dashboard
│   └── job_detail.html         # Job details with AI score breakdown & 1-click apply
├── tests/
│   ├── test_production_spec.py # Unit tests for auth, parsing, dual-engine ML & scoring
│   ├── test_fixes.py           # Regression tests for scoring edge cases & parsers
│   ├── test_dynamic_api.py     # Autocomplete, live resume updates & admin AJAX tests
│   └── test_naukri_shine_jobs.py # Real-time sync & quick apply integration tests
└── uploads/                    # Secure local storage for uploaded resume documents
```

---

## Quickstart & Installation

### 1. Prerequisites
- Python 3.11 or higher
- Git

### 2. Setup Virtual Environment
```bash
# Clone or navigate to the project directory
cd resume_ai_system

# Create and activate a virtual environment
python -m venv venv

# Windows:
.\venv\Scripts\activate

# Linux/macOS:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt

# Download spaCy language model
python -m spacy download en_core_web_sm
```

### 4. Run the Application
```bash
python app.py
```
Open your browser at **`http://127.0.0.1:5000`**.

### Default Administrator Credentials
- **Email:** `admin@resumeai.local`
- **Password:** `Admin@123`

---

## Running the Automated Test Suites

The test suite covers unit, integration, and ML scoring test cases:

```bash
# 1. Full Production Specification Suite (Auth, Magic Bytes, spaCy NER, Scoring Formula)
python tests/test_production_spec.py

# 2. Edge-case & Regression Tests
python tests/test_fixes.py

# 3. Dynamic Features & AJAX API Tests
python tests/test_dynamic_api.py

# 4. Job Sync & Application Flow Tests
python tests/test_naukri_shine_jobs.py
```

---

## AI/ML Customization & Model Swapping

### Tuning Scoring Formula Weights
In [config.py](file:///c:/Users/vasanth%20M/OneDrive/Desktop/ai_resume/resume_ai_system/config.py):
```python
# Match Scoring Formula Weights (Must sum to 1.0)
WEIGHT_SEMANTIC = 0.60           # Dense vector semantic similarity
WEIGHT_REQUIRED_COVERAGE = 0.30  # Exact required skill coverage
WEIGHT_EXPERIENCE = 0.10         # Experience fit bonus/penalty
```

### Swapping the Sentence-Transformers Model
The system uses `sentence-transformers/all-MiniLM-L6-v2` by default for its balance of speed (~15ms inference) and semantic accuracy.

To use another HuggingFace sentence transformer (e.g., `all-mpnet-base-v2`, `BAAI/bge-small-en-v1.5`, or `paraphrase-multilingual-MiniLM-L12-v2`):

1. Set the model name in your environment or update `config.py`:
   ```python
   EMBEDDING_MODEL_NAME = os.environ.get("EMBEDDING_MODEL_NAME", "all-mpnet-base-v2")
   ```
2. The model will automatically download and cache on first inference via `skill_matcher.get_embedding_model()`.
3. If internet access is restricted, download the model files and provide a local path:
   ```python
   EMBEDDING_MODEL_NAME = "C:/models/all-MiniLM-L6-v2"
   ```

---

---

## MySQL Database & Live Real-Time Job Ingestion

### 1. MySQL Connection Configuration
The application connects directly to the local MySQL server instance:
- **Host:** `localhost` (Port: `3306`)
- **Database:** `ai_resume`
- **Username:** `root`
- **Password:** `Vasanth@zenve`

All tables (`users`, `resumes`, `jobs`, `matches`, `applications`) are automatically initialized on application startup.

### 2. Zero Mock Data Policy (Real Live Job Feeds)
All mock and dummy data have been purged from the platform. The application dynamically aggregates real, active developer job postings from public feeds:
- **Remotive API** (`https://remotive.com/api/remote-jobs`)
- **Arbeitnow API** (`https://www.arbeitnow.com/api/job-board-api`)

Each real job posting is processed through the spaCy NLP pipeline to extract:
- Verified technical skills (canonicalized against the taxonomy)
- Seniority levels (Entry-Level, Mid-Level, Senior, Lead)
- Minimum years of experience
- Work modes (Remote, Hybrid, Onsite)
- Real employer metadata & application URLs

---

## Adzuna Jobs API Live Integration

The platform integrates the **Adzuna Jobs API** (`https://api.adzuna.com/v1/api/jobs/{country}/search/{page}`) as a live job-listing source, normalizing raw postings into the `jobs` schema so the AI skill-matching engine works uniformly against real market vacancies.

### 1. Account & Environment Setup
Sign up for a free developer account at [developer.adzuna.com](https://developer.adzuna.com/) to obtain an **App ID** and **App Key**.

Configure your environment variables:
```bash
# Windows PowerShell:
$env:ADZUNA_APP_ID="your_adzuna_app_id"
$env:ADZUNA_APP_KEY="your_adzuna_app_key"
$env:ADZUNA_COUNTRY="in"            # Country code (in, us, gb, au, etc.)
$env:ADZUNA_LIVE_SYNC_ENABLED="true" # Enforces startup check if live sync is required

# Linux/macOS:
export ADZUNA_APP_ID="your_adzuna_app_id"
export ADZUNA_APP_KEY="your_adzuna_app_key"
export ADZUNA_COUNTRY="in"
export ADZUNA_LIVE_SYNC_ENABLED="true"
```

> [!NOTE]
> **Graceful Degradation:** If `ADZUNA_APP_ID` or `ADZUNA_APP_KEY` are not set, the platform operates seamlessly using existing manual listings. The Admin portal shows a disabled *"Live sync not configured"* indicator rather than crashing. If `ADZUNA_LIVE_SYNC_ENABLED="true"` is explicitly set, the app will fail loudly at startup with an actionable error message.

### 2. Rate Limits & Free Tier Budgeting
- **Adzuna Free Tier Quota:** **250 requests per day** (~25 requests/minute).
- **Client Isolation:** Live API calls are **never** made during end-user `/jobs` requests.
- **In-Memory Caching:** Successful API responses are cached in memory for **15 minutes (900 seconds)** via `ADZUNA_CACHE_TTL_SECONDS`.
- **Sync Batch Strategy:** The default sync runs targeted developer queries (`python developer`, `data analyst`, `frontend developer`, `full stack engineer`, `devops engineer`) at 1 page of 20 results each (5 API requests total). A sync uses only ~2% of the daily allowance.

### 3. Skill & Experience Extraction from Unstructured Text
Adzuna provides free-text job descriptions rather than structured taxonomies. At ingestion time:
1. `adzuna_client.normalize_job()` strips HTML tags and normalizes fields (title, company, location, salary, dates, redirect URL).
2. `adzuna_client.enrich_job_with_skills()` executes the same NLP extraction pipeline used for resumes (`extract_skills()` + `extract_experience_years()`).
3. Skills are mapped to canonical taxonomies, and required experience is extracted from explicit requirements (e.g. *"3+ years of experience"* $\rightarrow$ `3.0`).
4. Listings with zero recognizable skills log a warning (`logger.warning`) to alert administrators.

### 4. Database UPSERT & Non-Destructive Soft Deletes
- **Deduplication:** Jobs are keyed on a composite unique index: `UNIQUE (source, external_id)`. Re-syncing existing vacancies updates title, salary, description, and `last_synced_at` without creating duplicate rows.
- **Soft-Deactivation:** Jobs that drop off the active Adzuna search results for more than 7 days are flagged as `is_active = 0`. Hard deletes are forbidden to maintain foreign key integrity with candidate match histories in the `matches` table.

### 5. Admin Controls & Manual Sync
- **Source Badges:** Jobs in `/admin/jobs` display distinct badges (`Adzuna` in blue vs. `Manual` / `Direct`).
- **Sync Button:** Administrators can trigger `POST /admin/jobs/sync` (or `/api/admin/jobs/sync`) via the **⚡ Sync Adzuna Jobs** button, accompanied by a live spinner and toast confirmation.
- **Read-Only Protection:** Synced Adzuna listings are read-only (direct editing is disabled to prevent sync overwrites), but administrators can freely hide/show them (`is_active` toggle) or inspect the external posting directly on Adzuna.

---

## Production Deployment (PostgreSQL / MySQL)

1. **MySQL Production:**
   Set environment variables or use the default `config.py` configuration:
   ```bash
   export DB_TYPE="mysql"
   export MYSQL_HOST="localhost"
   export MYSQL_USER="root"
   export MYSQL_PASSWORD="Vasanth@zenve"
   export MYSQL_DB="ai_resume"
   ```

2. **PostgreSQL Alternative:**
   ```bash
   psql -U postgres -d resume_ai_db -f schema_postgres.sql
   export DATABASE_URL="postgresql://user:password@localhost:5432/resume_ai_db"
   ```

3. **Run with Production WSGI Server:**
   ```bash
   gunicorn -w 4 -b 0.0.0.0:8000 "app:app"
   ```


