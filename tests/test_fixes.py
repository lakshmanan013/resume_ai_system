import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import sqlite3
import database
import models
import app
from skill_matcher import compute_match
from resume_parser import guess_name, extract_education

def test_all():
    print("=== 1. Testing skill_matcher.compute_match ===")
    res1 = compute_match(['gardening'], ['python', 'flask'], [])
    assert res1['score'] == 0.0, f"Expected 0.0, got {res1['score']}"
    print("Test 1 (0 required match, no preferred): PASS ->", res1['score'])

    res2 = compute_match(['python'], ['python', 'flask'], [])
    assert 48.0 <= res2['score'] <= 55.0, f"Expected ~50.0, got {res2['score']}"
    print("Test 2 (1/2 required match, no preferred): PASS ->", res2['score'])

    res3 = compute_match(['python', 'flask', 'docker'], ['python', 'flask'], ['docker'])
    assert res3['score'] >= 95.0, f"Expected >= 95.0, got {res3['score']}"
    print("Test 3 (all required + preferred): PASS ->", res3['score'])

    print("\n=== 2. Testing resume_parser.guess_name ===")
    name1 = guess_name("RESUME\nJohn Doe\njohn@example.com")
    assert name1 == "John Doe", f"Expected John Doe, got {name1}"
    print("Test 4 (RESUME header): PASS ->", name1)

    name2 = guess_name("CURRICULUM VITAE\nJane Smith\njane@example.com")
    assert name2 == "Jane Smith", f"Expected Jane Smith, got {name2}"
    print("Test 5 (CURRICULUM VITAE header): PASS ->", name2)

    print("\n=== 3. Testing resume_parser.extract_education ===")
    edu1 = extract_education("I will be graduating in May.")
    assert edu1 == [], f"Expected [], got {edu1}"
    print("Test 6 (will be sentence): PASS ->", edu1)

    edu2 = extract_education("Bachelor of Science in Computer Science, MIT")
    assert len(edu2) == 1, f"Expected 1 entry, got {edu2}"
    print("Test 7 (Bachelor of Science): PASS ->", edu2)

    print("\n=== 4. Testing models database operations ===")
    with app.app.app_context():
        db = database.get_db()
        # Create test user and resume
        db.execute("INSERT OR IGNORE INTO users (id, name, email, password_hash, role, is_active, created_at) VALUES (999, 'Test User', 'test999@test.com', 'hash', 'user', 1, '2026-01-01')")
        db.execute("INSERT OR IGNORE INTO resumes (id, user_id, filename, filepath, uploaded_at) VALUES (999, 999, 'test.pdf', 'uploads/test.pdf', '2026-01-01')")
        db.commit()

        # Test bulk_save_matches deduplication
        ranked = [{'id': 1, 'score': 80.0, 'matched_skills': ['python'], 'missing_skills': []}]
        models.bulk_save_matches(999, 999, ranked)
        count1 = db.execute("SELECT COUNT(*) c FROM matches WHERE user_id=999").fetchone()["c"]
        models.bulk_save_matches(999, 999, ranked)
        count2 = db.execute("SELECT COUNT(*) c FROM matches WHERE user_id=999").fetchone()["c"]
        assert count1 == 1 and count2 == 1, f"Deduplication failed: count1={count1}, count2={count2}"
        print("Test 8 (bulk_save_matches deduplication): PASS")

        # Test delete_job with matching records
        models.create_job("Test Job", "Test Co", "Remote", "Desc", ["python"], [], 0)
        test_job = db.execute("SELECT id FROM jobs WHERE title='Test Job'").fetchone()
        models.save_match(999, 999, test_job["id"], 90.0, ["python"], [])
        models.delete_job(test_job["id"])
        remaining = db.execute("SELECT COUNT(*) c FROM jobs WHERE id=?", (test_job["id"],)).fetchone()["c"]
        assert remaining == 0, "Job was not deleted"
        print("Test 9 (delete_job with matches FK safe): PASS")

        # Clean up test rows
        db.execute("DELETE FROM matches WHERE user_id=999")
        db.execute("DELETE FROM resumes WHERE id=999")
        db.execute("DELETE FROM users WHERE id=999")
        db.commit()

    print("\n==========================================")
    print("ALL 9 VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("==========================================")

if __name__ == "__main__":
    test_all()
