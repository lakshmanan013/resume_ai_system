import sqlite3
import json
from datetime import datetime, timezone
from flask import g, current_app
from werkzeug.security import generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',      -- 'user' or 'admin'
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resumes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    filepath TEXT NOT NULL,
    raw_text TEXT,
    parsed_name TEXT,
    email TEXT,
    phone TEXT,
    education TEXT,          -- JSON list
    skills TEXT,              -- JSON list
    experience_years REAL,
    uploaded_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT,
    description TEXT,
    required_skills TEXT,     -- JSON list
    preferred_skills TEXT,    -- JSON list
    min_experience REAL DEFAULT 0,
    job_type TEXT DEFAULT 'Full-Time',       -- 'Full-Time', 'Remote', 'Hybrid', 'Onsite'
    openings_count INTEGER DEFAULT 1,
    source TEXT DEFAULT 'Direct',            -- 'Naukri Live Feed', 'Shine Network', 'Direct Portal'
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    resume_id INTEGER NOT NULL,
    job_id INTEGER NOT NULL,
    score REAL NOT NULL,
    matched_skills TEXT,
    missing_skills TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
    FOREIGN KEY (resume_id) REFERENCES resumes (id) ON DELETE CASCADE,
    FOREIGN KEY (job_id) REFERENCES jobs (id) ON DELETE CASCADE
);
"""

# Rich real-time job listings inspired by Naukri & Shine portals
SAMPLE_JOBS = [
    # 1. Full Stack & Web
    dict(title="Senior Full Stack Engineer", company="Razorpay", location="Bangalore, KA",
         job_type="Hybrid", openings_count=4, source="Naukri Live Feed",
         description="Architect and build high-throughput payment gateways and checkout experiences using React, Node.js, and microservices.",
         required_skills=["javascript", "typescript", "react", "node.js", "rest api"],
         preferred_skills=["docker", "aws", "postgresql", "redis"], min_experience=3),
         
    dict(title="Frontend Engineer (React.js)", company="Swiggy", location="Bangalore, KA",
         job_type="Hybrid", openings_count=6, source="Shine Network",
         description="Build blazing-fast, responsive web interfaces for high-concurrency food delivery tracking and partner portals.",
         required_skills=["html", "css", "javascript", "react", "redux"],
         preferred_skills=["typescript", "tailwind css", "next.js", "webpack"], min_experience=2),

    dict(title="Backend Developer (Python / Django)", company="Zomato", location="Gurgaon, HR",
         job_type="Hybrid", openings_count=3, source="Naukri Live Feed",
         description="Develop resilient backend APIs handling millions of daily restaurant and order requests with Python and Postgres.",
         required_skills=["python", "django", "sql", "rest api", "git"],
         preferred_skills=["postgresql", "redis", "docker", "celery"], min_experience=2),

    dict(title="Lead Python API Developer", company="CRED", location="Bangalore, KA",
         job_type="Onsite", openings_count=2, source="Direct Portal",
         description="Design ultra-low-latency financial microservices and event-driven architectures with Python and FastAPI.",
         required_skills=["python", "fastapi", "sql", "microservices", "git"],
         preferred_skills=["kafka", "aws", "docker", "kubernetes"], min_experience=4),

    dict(title="Full Stack Software Engineer", company="Flipkart", location="Bangalore, KA",
         job_type="Hybrid", openings_count=8, source="Naukri Live Feed",
         description="Scale India's largest e-commerce platform across search, catalog, and checkout systems.",
         required_skills=["java", "javascript", "react", "spring boot", "sql"],
         preferred_skills=["kafka", "redis", "elasticsearch", "docker"], min_experience=2),

    dict(title="Software Development Engineer - II", company="Amazon", location="Hyderabad, TS",
         job_type="Hybrid", openings_count=12, source="Naukri Live Feed",
         description="Design and implement massive distributed cloud services for AWS and global fulfillment networks.",
         required_skills=["java", "c++", "data structures", "algorithms", "distributed systems"],
         preferred_skills=["aws", "docker", "ci/cd", "microservices"], min_experience=3),

    # 2. Data Science, AI & Machine Learning
    dict(title="Senior Data Scientist", company="Microsoft", location="Hyderabad, TS",
         job_type="Hybrid", openings_count=4, source="Shine Network",
         description="Build advanced predictive models and statistical algorithms powering Azure AI and enterprise solutions.",
         required_skills=["python", "machine learning", "pandas", "numpy", "statistics"],
         preferred_skills=["deep learning", "pytorch", "tensorflow", "scikit-learn"], min_experience=3),

    dict(title="AI / ML Engineer", company="Google", location="Bangalore, KA",
         job_type="Hybrid", openings_count=5, source="Naukri Live Feed",
         description="Train, optimize, and productionize large language models (LLMs) and computer vision pipelines at scale.",
         required_skills=["python", "machine learning", "deep learning", "tensorflow", "pytorch"],
         preferred_skills=["nlp", "computer vision", "kubernetes", "docker"], min_experience=3),

    dict(title="Data Analyst", company="PhonePe", location="Bangalore, KA",
         job_type="Hybrid", openings_count=5, source="Shine Network",
         description="Transform transaction logs into actionable product insights and interactive KPI dashboards.",
         required_skills=["sql", "python", "data analysis", "tableau", "excel"],
         preferred_skills=["power bi", "statistics", "pandas"], min_experience=1),

    dict(title="Computer Vision Engineer", company="Ola Electric", location="Bangalore, KA",
         job_type="Onsite", openings_count=3, source="Direct Portal",
         description="Develop real-time object detection and autonomous navigation perception algorithms.",
         required_skills=["python", "c++", "computer vision", "deep learning", "pytorch"],
         preferred_skills=["tensorflow", "linux", "edge ai"], min_experience=2),

    # 3. Cloud, DevOps & Infrastructure
    dict(title="DevOps & Platform Engineer", company="Atlassian", location="Remote",
         job_type="Remote", openings_count=4, source="Naukri Live Feed",
         description="Manage cloud infrastructure, automated CI/CD deployment pipelines, and multi-region Kubernetes clusters.",
         required_skills=["docker", "kubernetes", "aws", "ci/cd", "linux"],
         preferred_skills=["terraform", "ansible", "python", "jenkins"], min_experience=3),

    dict(title="Cloud Security & Infrastructure Engineer", company="Cisco", location="Pune, MH",
         job_type="Hybrid", openings_count=3, source="Shine Network",
         description="Harden enterprise networks, manage zero-trust architectures, and monitor cloud security compliance.",
         required_skills=["cybersecurity", "network security", "linux", "aws", "git"],
         preferred_skills=["penetration testing", "owasp", "terraform"], min_experience=2),

    dict(title="Site Reliability Engineer (SRE)", company="Uber", location="Hyderabad, TS",
         job_type="Hybrid", openings_count=4, source="Naukri Live Feed",
         description="Ensure 99.999% platform availability across global ride-sharing and food delivery systems.",
         required_skills=["linux", "python", "kubernetes", "docker", "ci/cd"],
         preferred_skills=["golang", "prometheus", "aws", "microservices"], min_experience=3),

    # 4. Mobile Engineering
    dict(title="Mobile App Developer (React Native)", company="Dream11", location="Mumbai, MH",
         job_type="Onsite", openings_count=3, source="Shine Network",
         description="Deliver ultra-smooth cross-platform mobile experiences capable of handling 10M+ concurrent sports fans.",
         required_skills=["react native", "javascript", "typescript", "rest api", "git"],
         preferred_skills=["redux", "ios", "android"], min_experience=2),

    dict(title="iOS Developer (Swift)", company="Paytm", location="Noida, UP",
         job_type="Hybrid", openings_count=4, source="Naukri Live Feed",
         description="Build intuitive, secure mobile banking and payment workflows for millions of daily active iOS users.",
         required_skills=["swift", "ios", "rest api", "git"],
         preferred_skills=["swift ui", "ci/cd", "unit testing"], min_experience=2),

    dict(title="Android Developer (Kotlin)", company="Jio Platforms", location="Mumbai, MH",
         job_type="Hybrid", openings_count=6, source="Shine Network",
         description="Architect cutting-edge Android applications for India's largest telecom and digital services network.",
         required_skills=["kotlin", "android", "rest api", "git"],
         preferred_skills=["java", "mvvm", "jetpack compose"], min_experience=2),

    # 5. UI/UX Design & Product
    dict(title="Product Designer (UI/UX)", company="Urban Company", location="Gurgaon, HR",
         job_type="Hybrid", openings_count=2, source="Direct Portal",
         description="Create seamless customer booking journeys and partner tools through user research and wireframing.",
         required_skills=["figma", "ui/ux design", "wireframing", "prototyping"],
         preferred_skills=["user research", "adobe xd", "design systems"], min_experience=2),

    dict(title="Technical Product Manager", company="InfoEdge", location="Noida, UP",
         job_type="Hybrid", openings_count=2, source="Naukri Live Feed",
         description="Define product roadmaps, lead agile engineering sprints, and drive algorithmic matching features.",
         required_skills=["product management", "agile", "scrum", "jira", "data analysis"],
         preferred_skills=["communication", "stakeholder management", "sql"], min_experience=3),

    # 6. IT Consulting & Enterprise
    dict(title="Java Cloud Developer", company="Infosys", location="Pune, MH",
         job_type="Hybrid", openings_count=15, source="Naukri Live Feed",
         description="Modernize legacy enterprise software systems into containerized Spring Boot cloud services.",
         required_skills=["java", "spring boot", "sql", "rest api", "git"],
         preferred_skills=["microservices", "docker", "aws", "oracle"], min_experience=2),

    dict(title="Database Administrator (PostgreSQL/Oracle)", company="TCS", location="Chennai, TN",
         job_type="Onsite", openings_count=8, source="Shine Network",
         description="Optimize enterprise SQL queries, manage database replication, backups, and disaster recovery.",
         required_skills=["postgresql", "oracle", "sql", "database design", "linux"],
         preferred_skills=["mysql", "redis", "bash"], min_experience=3),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()
    return None


def init_db(app):
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA)
        _migrate_columns(db)
        _seed(db)
        db.commit()


def _migrate_columns(db):
    """Safely adds missing columns to existing SQLite tables without data loss."""
    try:
        cursor = db.execute("PRAGMA table_info(jobs)")
        columns = [row["name"] for row in cursor.fetchall()]
        
        if "job_type" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN job_type TEXT DEFAULT 'Full-Time'")
        if "openings_count" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN openings_count INTEGER DEFAULT 1")
        if "source" not in columns:
            db.execute("ALTER TABLE jobs ADD COLUMN source TEXT DEFAULT 'Direct'")
        db.commit()
    except Exception as e:
        # Table might be freshly created by SCHEMA
        pass


def _seed(db):
    # Seed default admin if none exists
    admin = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()
    if not admin:
        db.execute(
            "INSERT INTO users (name, email, password_hash, role, is_active, created_at) "
            "VALUES (?, ?, ?, 'admin', 1, ?)",
            ("System Admin", "admin@resumeai.local",
             generate_password_hash("Admin@123"), datetime.now(timezone.utc).isoformat()),
        )

    # Seed sample jobs if empty
    count = db.execute("SELECT COUNT(*) AS c FROM jobs").fetchone()["c"]
    if count == 0:
        for job in SAMPLE_JOBS:
            db.execute(
                "INSERT INTO jobs (title, company, location, description, required_skills, "
                "preferred_skills, min_experience, job_type, openings_count, source, is_active, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (job["title"], job["company"], job["location"], job["description"],
                 json.dumps(job["required_skills"]), json.dumps(job["preferred_skills"]),
                 job["min_experience"], job.get("job_type", "Full-Time"),
                 job.get("openings_count", 1), job.get("source", "Naukri Live Feed"),
                 datetime.now(timezone.utc).isoformat()),
            )
    db.commit()


def register_db(app):
    app.teardown_appcontext(close_db)
