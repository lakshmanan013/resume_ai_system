"""
Unit and Integration Tests for Adzuna Jobs API Integration.

Covers:
1. Normalization of Adzuna raw payload fixtures (HTML stripping, date, salary, id mapping).
2. Skill and experience enrichment via NLP pipeline (extract_skills, extract_experience_years).
3. Zero-skill edge case warning behavior.
4. Database UPSERT deduplication on repeated syncs.
5. Soft-deactivation of stale listings without hard deletes.
6. Error handling: exponential retry on 5xx/timeout and custom AdzunaAPIError wrapping.
7. Graceful degradation when credentials are unset.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import requests

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from config import Config
import database
import models
import adzuna_client
from adzuna_client import (
    normalize_job,
    enrich_job_with_skills,
    clean_html,
    AdzunaAPIError,
    fetch_jobs,
    sync_jobs,
    clear_adzuna_cache,
)

SAMPLE_ADZUNA_FIXTURE = {
    "id": "adzuna_test_99881",
    "title": "<strong>Senior Python &amp; Flask Engineer</strong>",
    "company": {"display_name": "NextGen Cloud Labs"},
    "location": {"display_name": "Bangalore, India", "area": ["India", "Karnataka", "Bangalore"]},
    "description": (
        "<p>We are hiring an experienced <b>Python Developer</b> with at least 3+ years of experience. "
        "Candidate must have deep knowledge in Python, Flask, Docker, PostgreSQL, and Git. "
        "AWS or Kubernetes experience is a strong plus.</p>"
    ),
    "redirect_url": "https://www.adzuna.com/land/ad/99881?se=xyz",
    "salary_min": 1400000.0,
    "salary_max": 2200000.0,
    "created": "2026-09-18T08:30:00Z",
    "contract_time": "full_time"
}


class TestAdzunaIntegration(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_clean_html(self):
        """Verify HTML stripping and entity decoding."""
        raw = "<div>Hello &amp; welcome to <b>Resume AI</b>!</div>"
        cleaned = clean_html(raw)
        self.assertEqual(cleaned, "Hello & welcome to Resume AI!")

    def test_normalize_job(self):
        """Verify raw Adzuna dictionary correctly normalizes to application job schema."""
        normalized = normalize_job(SAMPLE_ADZUNA_FIXTURE)

        self.assertEqual(normalized["external_id"], "adzuna_test_99881")
        self.assertEqual(normalized["title"], "Senior Python & Flask Engineer")
        self.assertEqual(normalized["company"], "NextGen Cloud Labs")
        self.assertEqual(normalized["location"], "Bangalore, India")
        self.assertNotIn("<b>", normalized["description"])
        self.assertIn("Candidate must have deep knowledge", normalized["description"])
        self.assertEqual(normalized["source_url"], "https://www.adzuna.com/land/ad/99881?se=xyz")
        self.assertEqual(normalized["salary_min"], 1400000.0)
        self.assertEqual(normalized["salary_max"], 2200000.0)
        self.assertEqual(normalized["posted_at"], "2026-09-18T08:30:00Z")
        self.assertEqual(normalized["source"], "adzuna")
        self.assertEqual(normalized["job_type"], "Full-Time")

    def test_enrich_job_with_skills(self):
        """Verify unstructured job text is parsed and enriched with canonical skills and experience."""
        normalized = normalize_job(SAMPLE_ADZUNA_FIXTURE)
        enriched = enrich_job_with_skills(normalized)

        skills = enriched["required_skills"]
        self.assertIn("python", skills)
        self.assertIn("flask", skills)
        self.assertIn("docker", skills)
        self.assertIn("git", skills)
        self.assertEqual(enriched["min_experience"], 3.0)

    def test_enrich_job_zero_skills_warning(self):
        """Verify listings with zero skills do not crash and log a warning."""
        raw = {
            "id": "adzuna_zero_skills",
            "title": "General Office Helper",
            "company": {"display_name": "Local Business"},
            "location": {"display_name": "Delhi"},
            "description": "General paperwork handling and routine answering of telephone calls.",
            "redirect_url": "https://adzuna.com/ad/zero",
        }
        normalized = normalize_job(raw)
        with self.assertLogs("adzuna_client", level="WARNING") as cm:
            enriched = enrich_job_with_skills(normalized)

        self.assertEqual(enriched["required_skills"], [])
        self.assertTrue(any("extracted 0 canonical skills" in msg for msg in cm.output))

    def test_upsert_job_deduplication(self):
        """Verify upserting an Adzuna job multiple times updates the record without duplicating."""
        db = database.get_db()

        job_payload = {
            "title": "Data Analyst (Adzuna Test)",
            "company": "Analytics Corp",
            "location": "Remote, India",
            "description": "Requires SQL, Python, Tableau with 2+ years of experience.",
            "required_skills": ["sql", "python", "tableau"],
            "preferred_skills": [],
            "min_experience": 2.0,
            "job_type": "Remote",
            "seniority_level": "Mid-Level",
            "openings_count": 1,
            "source": "adzuna",
            "external_id": "test_ext_dedup_001",
            "source_url": "https://adzuna.com/job/001",
            "salary_min": 600000.0,
            "salary_max": 900000.0,
            "posted_at": "2026-09-18T00:00:00Z"
        }

        # First insert
        first_res = models.upsert_job(job_payload)
        self.assertIsNotNone(first_res)

        # Verify 1 record in DB
        rows = db.execute("SELECT * FROM jobs WHERE source='adzuna' AND external_id='test_ext_dedup_001'").fetchall()
        self.assertEqual(len(rows), 1)
        initial_id = rows[0]["id"]

        # Second upsert with updated salary and title
        job_payload["title"] = "Senior Data Analyst (Adzuna Test)"
        job_payload["salary_max"] = 1200000.0
        second_res = models.upsert_job(job_payload)
        self.assertIsNotNone(second_res)

        # Verify still 1 record with identical ID, but updated values
        rows_after = db.execute("SELECT * FROM jobs WHERE source='adzuna' AND external_id='test_ext_dedup_001'").fetchall()
        self.assertEqual(len(rows_after), 1)
        self.assertEqual(rows_after[0]["id"], initial_id)
        self.assertEqual(rows_after[0]["title"], "Senior Data Analyst (Adzuna Test)")
        self.assertEqual(float(rows_after[0]["salary_max"]), 1200000.0)

        # Cleanup
        db.execute("DELETE FROM jobs WHERE external_id='test_ext_dedup_001'")
        db.commit()

    def test_soft_deactivation_stale_jobs(self):
        """Verify stale Adzuna jobs disappearing from feed are marked is_active=0 rather than deleted."""
        db = database.get_db()

        # Seed two jobs with last_synced_at older than 10 days
        stale_date = "2026-09-01T00:00:00+00:00"
        job_a = {
            "title": "Adzuna Active Role",
            "company": "Company A",
            "location": "Bangalore",
            "description": "Python role",
            "required_skills": ["python"],
            "source": "adzuna",
            "external_id": "ext_active_100",
            "last_synced_at": stale_date
        }
        job_b = {
            "title": "Adzuna Stale Role",
            "company": "Company B",
            "location": "Mumbai",
            "description": "Java role",
            "required_skills": ["java"],
            "source": "adzuna",
            "external_id": "ext_stale_200",
            "last_synced_at": stale_date
        }
        models.upsert_job(job_a)
        models.upsert_job(job_b)

        # Force last_synced_at to 10 days ago
        db.execute("UPDATE jobs SET last_synced_at = ? WHERE external_id IN ('ext_active_100', 'ext_stale_200')",
                   (stale_date,))
        db.commit()

        # Simulate sync where only ext_active_100 was returned
        deactivated_count = models.soft_deactivate_stale_adzuna_jobs(
            active_external_ids={"ext_active_100"},
            cutoff_days=7
        )
        self.assertGreaterEqual(deactivated_count, 1)

        # Check statuses
        row_a = db.execute("SELECT is_active FROM jobs WHERE external_id='ext_active_100'").fetchone()
        row_b = db.execute("SELECT is_active FROM jobs WHERE external_id='ext_stale_200'").fetchone()

        self.assertEqual(row_a["is_active"], 1)
        self.assertEqual(row_b["is_active"], 0)  # Stale job is deactivated

        # Cleanup
        db.execute("DELETE FROM jobs WHERE external_id IN ('ext_active_100', 'ext_stale_200')")
        db.commit()

    @patch("requests.get")
    def test_fetch_jobs_retry_on_timeout(self, mock_get):
        """Verify fetch_jobs retries once on timeout and succeeds on second attempt."""
        clear_adzuna_cache()
        mock_success = MagicMock()
        mock_success.ok = True
        mock_success.status_code = 200
        mock_success.json.return_value = {"results": [SAMPLE_ADZUNA_FIXTURE]}

        mock_get.side_effect = [requests.exceptions.Timeout("Connection timed out"), mock_success]

        with patch.object(Config, "ADZUNA_APP_ID", "test_id"), patch.object(Config, "ADZUNA_APP_KEY", "test_key"):
            data = fetch_jobs(query="python", location="Bangalore")
            self.assertEqual(len(data["results"]), 1)
            self.assertEqual(mock_get.call_count, 2)

    @patch("requests.get")
    def test_fetch_jobs_raises_adzuna_api_error_on_5xx(self, mock_get):
        """Verify HTTP 500 server errors raise custom AdzunaAPIError after retry."""
        clear_adzuna_cache()
        mock_500 = MagicMock()
        mock_500.ok = False
        mock_500.status_code = 500
        mock_500.text = "Internal Server Error"
        mock_get.return_value = mock_500

        with patch.object(Config, "ADZUNA_APP_ID", "test_id"), patch.object(Config, "ADZUNA_APP_KEY", "test_key"):
            with self.assertRaises(AdzunaAPIError) as exc_info:
                fetch_jobs(query="python")
            self.assertIn("server error 500", str(exc_info.exception).lower())

    def test_sync_jobs_graceful_degradation_without_credentials(self):
        """Verify sync_jobs degrades gracefully with an informative error when credentials are not set."""
        with patch.object(Config, "ADZUNA_APP_ID", ""), patch.object(Config, "ADZUNA_APP_KEY", ""):
            result = sync_jobs()
            self.assertFalse(result["success"])
            self.assertIn("not configured", result["message"])
            self.assertEqual(result["synced"], 0)


if __name__ == "__main__":
    unittest.main()
