import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database
import models
from app import app

def test_dynamic_features():
    print("=== Testing Dynamic Features & APIs ===")
    
    with app.test_client() as client:
        with app.app_context():
            db = database.get_db()
            
            # Setup test user and admin
            db.execute("INSERT OR REPLACE INTO users (id, name, email, password_hash, role, is_active, created_at) "
                       "VALUES (101, 'Dynamic User', 'dyn@test.com', 'hash', 'user', 1, '2026-01-01')")
            db.execute("INSERT OR REPLACE INTO users (id, name, email, password_hash, role, is_active, created_at) "
                       "VALUES (102, 'Dynamic Admin', 'admin_dyn@test.com', 'hash', 'admin', 1, '2026-01-01')")
            
            # Setup test resume
            parsed = {
                "raw_text": "Sample text with python and sql",
                "name": "Dynamic User",
                "email": "dyn@test.com",
                "phone": "555-1234",
                "education": ["B.Sc Computer Science"],
                "skills": ["python", "sql"],
                "experience_years": 2.0
            }
            resume_id = models.save_resume(101, "resume.pdf", "uploads/resume.pdf", parsed)
            
            # Setup test job
            models.create_job("Fullstack Python Lead", "Apex Tech", "Remote", "Lead Python Developer",
                              ["python", "flask", "docker"], ["aws", "kubernetes"], 3.0)
            test_job = db.execute("SELECT * FROM jobs WHERE title='Fullstack Python Lead'").fetchone()
            db.commit()

        # 1. Test Autocomplete Suggestions API
        print("\n--- 1. Testing GET /api/skills/suggestions ---")
        res = client.get("/api/skills/suggestions?q=py")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.get_json()
        assert "python" in data["skills"] or "pytorch" in data["skills"], "Expected python in suggestions"
        print("[PASS] Autocomplete API returned matching skills:", data["skills"][:3])

        # 2. Test Resume Dynamic Update API (Adding skills on the fly)
        print("\n--- 2. Testing POST /api/resume/<id>/update ---")
        with client.session_transaction() as sess:
            sess["user_id"] = 101
            sess["role"] = "user"
            sess["name"] = "Dynamic User"

        update_payload = {
            "skills": ["python", "sql", "docker", "flask"],
            "experience_years": 3.0,
            "parsed_name": "Dynamic User Updated"
        }
        res = client.post(f"/api/resume/{resume_id}/update",
                          data=json.dumps(update_payload),
                          content_type="application/json")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        data = res.get_json()
        assert data["success"] is True
        assert "flask" in data["resume"]["skills"]
        assert data["resume"]["parsed_name"] == "Dynamic User Updated"
        assert len(data["ranked_jobs"]) > 0
        print("[PASS] Dynamic resume update successful! Recalculated top score:", data["ranked_jobs"][0]["score"])

        # 3. Test What-If Simulator API
        print("\n--- 3. Testing POST /api/resume/<id>/simulate-skill ---")
        sim_payload = {
            "extra_skills": ["aws", "kubernetes"],
            "job_id": test_job["id"]
        }
        res = client.post(f"/api/resume/{resume_id}/simulate-skill",
                          data=json.dumps(sim_payload),
                          content_type="application/json")
        assert res.status_code == 200
        sim_data = res.get_json()
        assert sim_data["success"] is True
        assert sim_data["simulated_match"]["score"] >= sim_data["original_match"]["score"]
        print(f"[PASS] What-If Simulator: Original {sim_data['original_match']['score']}% -> Simulated {sim_data['simulated_match']['score']}% (+{sim_data['diff']}%)")

        # 4. Test Admin AJAX Endpoints
        print("\n--- 4. Testing Admin AJAX Endpoints ---")
        with client.session_transaction() as sess:
            sess["user_id"] = 102
            sess["role"] = "admin"
            sess["name"] = "Dynamic Admin"

        # Toggle user active status
        res = client.post("/api/admin/users/101/toggle")
        assert res.status_code == 200
        toggle_data = res.get_json()
        assert toggle_data["success"] is True
        assert toggle_data["is_active"] is False
        print("[PASS] Admin AJAX toggle user active status: SUCCESS (is_active=False)")

        # Toggle job visibility
        res = client.post(f"/api/admin/jobs/{test_job['id']}/toggle")
        assert res.status_code == 200
        job_toggle = res.get_json()
        assert job_toggle["success"] is True
        assert job_toggle["is_active"] is False
        print("[PASS] Admin AJAX toggle job visibility: SUCCESS (is_active=False)")

        # Admin stats API
        res = client.get("/api/admin/stats")
        assert res.status_code == 200
        stats = res.get_json()
        assert "total_users" in stats and "total_resumes" in stats
        print("[PASS] Admin stats API: SUCCESS (total users:", stats["total_users"], ")")

        # Delete job via AJAX
        res = client.post(f"/api/admin/jobs/{test_job['id']}/delete")
        assert res.status_code == 200
        del_data = res.get_json()
        assert del_data["success"] is True
        print("[PASS] Admin AJAX delete job: SUCCESS")

        # Clean up test rows
        with app.app_context():
            db = database.get_db()
            db.execute("DELETE FROM matches WHERE user_id=101")
            db.execute("DELETE FROM resumes WHERE user_id=101")
            db.execute("DELETE FROM users WHERE id IN (101, 102)")
            db.commit()

    print("\n==========================================")
    print("ALL DYNAMIC API TESTS PASSED SUCCESSFULLY!")
    print("==========================================")

if __name__ == "__main__":
    test_dynamic_features()
