-- ============================================================
-- Resume AI - Production PostgreSQL Schema
-- ============================================================

-- Users table with rate limiting and reset tokens
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL DEFAULT 'user',  -- 'user' or 'admin'
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    failed_attempts INT NOT NULL DEFAULT 0,
    locked_until TIMESTAMPTZ,
    reset_token VARCHAR(255),
    reset_token_expiry TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Versioned resumes table
CREATE TABLE IF NOT EXISTS resumes (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    filepath TEXT NOT NULL,
    raw_text TEXT,
    parsed_name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(100),
    education JSONB DEFAULT '[]'::jsonb,
    skills JSONB DEFAULT '[]'::jsonb,
    parsed_json JSONB DEFAULT '{}'::jsonb,
    skills_json JSONB DEFAULT '[]'::jsonb,
    experience_years NUMERIC(4, 1),
    version INT NOT NULL DEFAULT 1,
    is_confirmed BOOLEAN NOT NULL DEFAULT FALSE,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_resumes_user_id ON resumes(user_id);
CREATE INDEX IF NOT EXISTS idx_resumes_uploaded_at ON resumes(uploaded_at DESC);

-- Jobs table
CREATE TABLE IF NOT EXISTS jobs (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    company VARCHAR(255) NOT NULL,
    location VARCHAR(255),
    description TEXT,
    required_skills JSONB DEFAULT '[]'::jsonb,
    preferred_skills JSONB DEFAULT '[]'::jsonb,
    required_skills_json JSONB DEFAULT '[]'::jsonb,
    preferred_skills_json JSONB DEFAULT '[]'::jsonb,
    min_experience NUMERIC(4, 1) DEFAULT 0,
    job_type VARCHAR(50) DEFAULT 'Full-Time',       -- 'Full-Time', 'Remote', 'Hybrid', 'Onsite'
    seniority_level VARCHAR(50) DEFAULT 'Mid-Level', -- 'Entry-Level', 'Mid-Level', 'Senior', 'Lead'
    openings_count INT DEFAULT 1,
    source VARCHAR(100) DEFAULT 'Direct',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_is_active ON jobs(is_active);
CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);

-- Matches audit and reporting table
CREATE TABLE IF NOT EXISTS matches (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    resume_id INT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
    job_id INT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    score NUMERIC(5, 2) NOT NULL,
    matched_skills JSONB DEFAULT '[]'::jsonb,
    missing_skills JSONB DEFAULT '[]'::jsonb,
    matched_skills_json JSONB DEFAULT '[]'::jsonb,
    missing_skills_json JSONB DEFAULT '[]'::jsonb,
    explanation TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_matches_user_id ON matches(user_id);
CREATE INDEX IF NOT EXISTS idx_matches_resume_id ON matches(resume_id);
CREATE INDEX IF NOT EXISTS idx_matches_job_id ON matches(job_id);
CREATE INDEX IF NOT EXISTS idx_matches_score ON matches(score DESC);
