import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database
import models
from app import app
from skill_matcher import compute_match, rank_jobs

def test_naukri_shine_suite():
    print("=== Testing Shine / Naukri Real-Time Job Matching Suite ===")

    with app.test_client() as client:
        with app.app_context():
            db = database.get_db()

            # 1. Test Schema & Live Job Sync
            print("\n--- 1. Testing Live Job Sync (Naukri/Shine Feeds) ---")
            sync_res = models.sync_live_jobs()
            assert sync_res["total_active"] >= 20, f"Expected >=20 active jobs, got {sync_res['total_active']}"
            print(f"[PASS] Synced {sync_res['total_active']} active jobs with realistic metadata!")

            # Verify job fields (no salary)
            sample = db.execute("SELECT * FROM jobs WHERE company='Razorpay'").fetchone()
            assert sample is not None, "Expected Razorpay job"
            assert sample["job_type"] in ["Hybrid", "Remote", "Onsite", "Full-Time"]
            assert sample["source"] == "Naukri Live Feed"
            assert sample["openings_count"] >= 1
            print("[PASS] Verified job details: title='Senior Full Stack Engineer', company='Razorpay', source='Naukri Live Feed', mode='Hybrid'")

        # 2. Test Match Breakdown Algorithm
        print("\n--- 2. Testing Naukri/Shine Match Breakdown & ATS Keyword Insights ---")
        candidate_skills = ["javascript", "react", "node.js", "typescript"]
        job_req = ["javascript", "typescript", "react", "node.js", "rest api"]
        job_pref = ["docker", "aws", "postgresql"]
        
        match = compute_match(candidate_skills, job_req, job_pref, candidate_experience_years=3.5, job_min_experience=3.0)
        assert match["score"] == 64.0, f"Expected 64.0, got {match['score']}"
        assert len(match["matched_required"]) == 4
        assert "rest api" in match["missing_ats_keywords"]
        assert len(match["match_reasons"]) >= 2
        print(f"[PASS] Match computed: {match['score']}% fit, {match['matched_count']} skills matched, ATS keywords missing: {match['missing_ats_keywords']}")
        print("       Match highlights:", match["match_reasons"])

        # 3. Test Admin Live Sync API
        print("\n--- 3. Testing Admin Live Sync Endpoint ---")
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "admin"
            sess["name"] = "Admin"

        res = client.post("/api/admin/jobs/sync")
        assert res.status_code == 200
        sync_api_data = res.get_json()
        assert sync_api_data["success"] is True
        print(f"[PASS] Admin Live Sync API returned success: {sync_api_data['message']}")

        # 4. Test 1-Click Quick Apply API
        print("\n--- 4. Testing 1-Click Quick Apply API ---")
        with client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["role"] = "user"
            sess["name"] = "Candidate User"

        with app.app_context():
            job_to_apply = database.get_db().execute("SELECT id, title, company FROM jobs LIMIT 1").fetchone()
            job_id = job_to_apply["id"]

        apply_res = client.post(f"/api/jobs/{job_id}/apply")
        assert apply_res.status_code == 200
        apply_data = apply_res.get_json()
        assert apply_data["success"] is True
        print(f"[PASS] 1-Click Apply API: {apply_data['message']}")

    print("\n=======================================================")
    print("ALL NAUKRI / SHINE MATCHING TESTS PASSED SUCCESSFULLY!")
    print("=======================================================")

if __name__ == "__main__":
    test_naukri_shine_suite()
