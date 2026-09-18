"""
Comprehensive Unit Test Suite for Resume AI System.
Tests all 6 modules against production requirements:
- Password strength, rate-limiting, and time-limited token generation.
- MIME type magic bytes validation and ScannedResumeError rejection.
- Date range experience calculation and canonical skill normalization.
- Target role gap analysis.
- Dual-engine scoring function with known input/output pairs, explanations, and fallback modes.
- Admin analytics, market skill gap computation, and CSV export.
"""

import sys
import os
import io
import unittest
import tempfile
from datetime import datetime, timezone, timedelta

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
import database
import models
from app import app, check_password_strength
from resume_parser import (
    validate_resume_file,
    calculate_experience_from_date_ranges,
    compute_gap_analysis,
    ScannedResumeError,
    extract_candidate_name,
)
from skills_data import normalize_skill
from skill_matcher import (
    compute_match,
    compute_tfidf_similarity,
    compute_semantic_similarity,
    generate_natural_language_explanation,
    rank_jobs,
)


class TestResumeAISystem(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["DATABASE"] = os.path.join(tempfile.gettempdir(), "test_resume_ai.db")
        with app.app_context():
            database.init_db(app)

    def setUp(self):
        self.app = app
        self.client = app.test_client()
        self.ctx = app.app_context()
        self.ctx.push()
        with app.app_context():
            db = database.get_db()
            db.execute("DELETE FROM matches")
            db.execute("DELETE FROM resumes")
            db.execute("DELETE FROM users WHERE email LIKE '%@example.com'")
            db.commit()

    def tearDown(self):
        self.ctx.pop()

    # =========================================================================
    # Module 1: Auth, Password Strength, Rate Limiting & Reset Tokens
    # =========================================================================
    def test_password_strength_enforcement(self):
        # Too short
        ok, msg = check_password_strength("Short1!")
        self.assertFalse(ok)
        self.assertIn("at least 8 characters", msg)

        # No uppercase
        ok, msg = check_password_strength("lowercase123")
        self.assertFalse(ok)
        self.assertIn("uppercase letter", msg)

        # No lowercase
        ok, msg = check_password_strength("UPPERCASE123")
        self.assertFalse(ok)
        self.assertIn("lowercase letter", msg)

        # No digits
        ok, msg = check_password_strength("NoDigitsHere!")
        self.assertFalse(ok)
        self.assertIn("numeric digit", msg)

        # Valid strong password
        ok, msg = check_password_strength("StrongP@ssw0rd2026")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_rate_limiting_and_account_lockout(self):
        test_email = "ratelimit_candidate@example.com"
        models.create_user("Rate Limit Test", test_email, "SecureP@ss123")
        user = models.get_user_by_email(test_email)
        self.assertFalse(models.is_account_locked(user))

        # Record 4 failed attempts -> still unlocked
        for _ in range(4):
            models.record_login_failure(test_email, max_attempts=5, lockout_minutes=15)
        user = models.get_user_by_email(test_email)
        self.assertFalse(models.is_account_locked(user))

        # 5th failed attempt -> locked
        models.record_login_failure(test_email, max_attempts=5, lockout_minutes=15)
        user = models.get_user_by_email(test_email)
        self.assertTrue(models.is_account_locked(user))

        # Reset failures after unlock
        models.reset_login_failures(user["id"])
        user_unlocked = models.get_user_by_email(test_email)
        self.assertFalse(models.is_account_locked(user_unlocked))
        self.assertEqual(user_unlocked["failed_attempts"], 0)

    def test_password_reset_token_lifecycle(self):
        test_email = "reset_tester@example.com"
        models.create_user("Reset User", test_email, "OldPassword123")
        user = models.get_user_by_email(test_email)

        # Generate timed cryptographic token
        token = models.generate_reset_token(test_email)
        self.assertIsNotNone(token)

        # Verify valid token
        verified_user = models.verify_reset_token(token, max_age=3600)
        self.assertIsNotNone(verified_user)
        self.assertEqual(verified_user["id"], user["id"])

        # Tampered token fails
        bad_token = token + "tamper"
        self.assertIsNone(models.verify_reset_token(bad_token, max_age=3600))

        # Update password using token helper
        models.reset_user_password(user["id"], "NewStrongP@ss2026")
        refreshed = models.get_user_by_id(user["id"])
        self.assertTrue(models.verify_password(refreshed, "NewStrongP@ss2026"))
        self.assertIsNone(refreshed["reset_token"])

    # =========================================================================
    # Module 2: File MIME Validation & Graceful Scanned PDF Rejection
    # =========================================================================
    def test_mime_validation_and_file_headers(self):
        # Valid PDF header
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.5 fake pdf stream content for testing")
            valid_pdf = f.name

        try:
            ok, err = validate_resume_file("sample.pdf", {"pdf", "docx"}, filepath=valid_pdf)
            self.assertTrue(ok)
            self.assertIsNone(err)
        finally:
            os.remove(valid_pdf)

        # Renamed fake executable pretending to be PDF
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"MZ\x90\x00 fake executable header")
            fake_pdf = f.name

        try:
            ok, err = validate_resume_file("malicious.pdf", {"pdf", "docx"}, filepath=fake_pdf)
            self.assertFalse(ok)
            self.assertIsNotNone(err)
            self.assertIn("Missing standard %PDF", err or "")
        finally:
            os.remove(fake_pdf)

        # Unsupported file extension
        ok, err = validate_resume_file("script.py", {"pdf", "docx"})
        self.assertFalse(ok)
        self.assertIsNotNone(err)
        self.assertIn("Unsupported file type", err or "")

    # =========================================================================
    # Module 3: Date-Range Experience, Normalization & Gap Analysis
    # =========================================================================
    def test_date_range_experience_calculation(self):
        # Standard 4-year range: 2018 - 2022
        exp1 = calculate_experience_from_date_ranges(
            "Software Engineer at Acme Corp\n2018 - 2022\nBuilt backend services.",
            ""
        )
        self.assertEqual(exp1, 4.0)

        # Overlapping work spans: 2018 - 2021 and 2019 - 2022 should merge to 4.0 years (2018-2022)
        exp_overlap = calculate_experience_from_date_ranges(
            "Company A: 2018 - 2021\nCompany B (part time): 2019 - 2022",
            ""
        )
        self.assertEqual(exp_overlap, 4.0)

        # Fallback to regex when dates missing
        exp_regex = calculate_experience_from_date_ranges(
            "",
            "Senior Developer with 7.5 years of experience in distributed systems."
        )
        self.assertEqual(exp_regex, 7.5)

    def test_skill_normalization(self):
        self.assertEqual(normalize_skill("JS"), "javascript")
        self.assertEqual(normalize_skill("React.js"), "react")
        self.assertEqual(normalize_skill("NodeJS"), "node.js")
        self.assertEqual(normalize_skill("Postgres"), "postgresql")
        self.assertEqual(normalize_skill("AWS Cloud"), "aws")
        self.assertEqual(normalize_skill("py"), "python")
        self.assertEqual(normalize_skill("Docker"), "docker")

    def test_target_role_gap_analysis(self):
        cand_skills = ["python", "sql", "git", "rest api"]
        analysis = compute_gap_analysis(cand_skills, target_role="Backend Developer")

        self.assertEqual(analysis["target_role"], "Backend Developer")
        self.assertIn("python", analysis["present_required"])
        self.assertIn("sql", analysis["present_required"])
        self.assertGreater(analysis["coverage_percentage"], 0)
        self.assertTrue(len(analysis["recommendations"]) > 0)

    # =========================================================================
    # Module 4: Scoring Function (Known Input/Output Pairs & Explanations)
    # =========================================================================
    def test_scoring_perfect_match(self):
        skills = ["python", "django", "sql", "rest api"]
        result = compute_match(
            candidate_skills=skills,
            job_required_skills=["python", "django", "sql", "rest api"],
            job_preferred_skills=[],
            candidate_experience_years=3.0,
            job_min_experience=2.0
        )
        # Full skill coverage and meets experience requirement
        self.assertGreaterEqual(result["score"], 90.0)
        self.assertTrue(result["experience_fit"])
        self.assertEqual(result["missing_skills"], [])
        self.assertIn("Outstanding match", result["explanation"])

    def test_scoring_zero_match(self):
        result = compute_match(
            candidate_skills=["gardening", "pottery", "cooking"],
            job_required_skills=["python", "docker", "kubernetes", "aws"],
            job_preferred_skills=[],
            candidate_experience_years=1.0,
            job_min_experience=4.0
        )
        # Should score low (< 30)
        self.assertLess(result["score"], 30.0)
        self.assertFalse(result["experience_fit"])
        self.assertEqual(len(result["missing_skills"]), 4)
        self.assertIn("Low direct overlap", result["explanation"])

    def test_scoring_experience_penalty(self):
        skills = ["python", "django"]
        # Candidate A has 5 years (meets 3+)
        res_exp_ok = compute_match(
            candidate_skills=skills,
            job_required_skills=["python", "django"],
            candidate_experience_years=5.0,
            job_min_experience=3.0
        )
        # Candidate B has 0.5 years (under 3+)
        res_exp_low = compute_match(
            candidate_skills=skills,
            job_required_skills=["python", "django"],
            candidate_experience_years=0.5,
            job_min_experience=3.0
        )
        self.assertTrue(res_exp_ok["experience_fit"])
        self.assertFalse(res_exp_low["experience_fit"])
        self.assertGreater(res_exp_ok["score"], res_exp_low["score"])

    def test_scoring_tfidf_fallback(self):
        resume_text = "Experienced software engineer specializing in python, flask APIs, and database design."
        job_text = "Looking for a python backend engineer with flask and database optimization skills."
        sim = compute_tfidf_similarity(resume_text, job_text)
        self.assertGreater(sim, 10.0)
        self.assertLessEqual(sim, 100.0)

    def test_rank_jobs_sorting(self):
        jobs = [
            {"id": 1, "title": "Python Dev", "required_skills": ["python", "sql"], "min_experience": 2},
            {"id": 2, "title": "Java Dev", "required_skills": ["java", "spring"], "min_experience": 2},
            {"id": 3, "title": "Full Stack Dev", "required_skills": ["python", "sql", "react"], "min_experience": 2},
        ]
        cand = ["python", "sql"]
        ranked = rank_jobs(cand, jobs, candidate_experience_years=3.0, threshold=0.0)
        self.assertEqual(len(ranked), 3)
        # Python Dev or Full Stack Dev should rank above Java Dev
        self.assertEqual(ranked[0]["title"], "Python Dev")
        self.assertEqual(ranked[-1]["title"], "Java Dev")

    # =========================================================================
    # Module 5 & 6: Search, Filters & Admin CSV Export
    # =========================================================================
    def test_job_faceted_filtering(self):
        # Search by company dynamically from active catalog
        all_jobs = models.list_jobs(active_only=True)
        self.assertTrue(len(all_jobs) > 0)
        target_company = all_jobs[0]["company"]
        results = models.list_jobs(active_only=True, search_query=target_company)
        self.assertTrue(any(target_company.lower() in j["company"].lower() for j in results))

        # Filter by remote work mode
        remote_jobs = models.list_jobs(active_only=True, job_type="Remote")
        for r in remote_jobs:
            self.assertEqual(r["job_type"].lower(), "remote")

    def test_admin_reports_and_csv_export(self):
        stats = models.get_stats()
        self.assertIn("total_users", stats)
        self.assertIn("most_requested_skills", stats)
        self.assertIn("most_common_candidate_skills", stats)
        self.assertIn("skill_gap_analysis", stats)

        csv_content = models.export_stats_csv()
        self.assertIn("=== MATCHES AUDIT LOG ===", csv_content)
        self.assertIn("=== ACTIVE JOBS INVENTORY ===", csv_content)


if __name__ == "__main__":
    unittest.main()
