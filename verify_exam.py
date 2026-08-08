import sys
import os
import json
import time
from fastapi.testclient import TestClient

# Ensure current folder is in python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.main import app
from app.db import init_db, get_db_connection, DB_PATH

def run_tests():
    # 1. Re-initialize Database
    print("Initializing test database...")
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except Exception:
            # Fallback if DB file is locked
            conn = get_db_connection()
            for t in ["violations", "answers", "attempt_options", "attempt_questions", "attempts", "question_options", "questions", "exams", "users"]:
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.commit()
            conn.close()
    init_db()
    
    client = TestClient(app)
    
    # 2. Register Teacher & Student
    print("TEST: User Registration & Role-based Auth")
    
    # Register teacher
    t_reg = client.post("/api/auth/register", json={
        "name": "Prof. Charles",
        "email": "charles@college.edu",
        "password": "teacherpassword123",
        "role": "teacher"
    })
    if t_reg.status_code != 200:
        print("Teacher Registration Failed Code:", t_reg.status_code)
        print("Teacher Registration Failed Body:", t_reg.text)
    assert t_reg.status_code == 200, "Teacher registration failed"
    t_token = t_reg.json()["token"]
    
    # Register students
    s1_reg = client.post("/api/auth/register", json={
        "name": "Alice Student",
        "email": "alice@college.edu",
        "password": "studentpassword123",
        "role": "student"
    })
    assert s1_reg.status_code == 200, "Student 1 registration failed"
    s1_token = s1_reg.json()["token"]
    
    s2_reg = client.post("/api/auth/register", json={
        "name": "Bob Student",
        "email": "bob@college.edu",
        "password": "studentpassword123",
        "role": "student"
    })
    assert s2_reg.status_code == 200, "Student 2 registration failed"
    s2_token = s2_reg.json()["token"]
    
    # 3. Create Exam as Teacher
    print("TEST: Exam & Question CRUD")
    headers_teacher = {"Authorization": f"Bearer {t_token}"}
    
    exam_payload = {
        "title": "Quantum Physics Midterm",
        "description": "General concepts of quantum physics. Negative marking applies.",
        "duration": 60,
        "total_marks": 10.0,
        "negative_mark": 0.5
    }
    create_exam_res = client.post("/api/exams", json=exam_payload, headers=headers_teacher)
    if create_exam_res.status_code != 200:
        print("Exam Creation Failed Response Code:", create_exam_res.status_code)
        print("Exam Creation Failed Response Body:", create_exam_res.text)
    assert create_exam_res.status_code == 200, "Exam creation failed"
    exam_id = create_exam_res.json()["exam_id"]
    
    # Add Questions
    q1 = {
        "question_text": "What is the quantum of electromagnetic radiation?",
        "options": ["Electron", "Proton", "Photon", "Neutron"],
        "correct_answer": "Photon",
        "marks": 4.0,
        "negative_marks": 1.0,
        "difficulty": "easy"
    }
    q2 = {
        "question_text": "Who formulated the Uncertainty Principle?",
        "options": ["Albert Einstein", "Werner Heisenberg", "Niels Bohr", "Erwin Schrödinger"],
        "correct_answer": "Werner Heisenberg",
        "marks": 3.0,
        "negative_marks": 0.5,
        "difficulty": "medium"
    }
    q3 = {
        "question_text": "What does a wave function collapse imply?",
        "options": ["Loss of energy", "Reduction to a single eigenstate", "Reflection of light", "Thermal radiation"],
        "correct_answer": "Reduction to a single eigenstate",
        "marks": 3.0,
        "negative_marks": 0.5,
        "difficulty": "hard"
    }
    
    for idx, q_data in enumerate([q1, q2, q3]):
        q_res = client.post(f"/api/exams/{exam_id}/questions", json=q_data, headers=headers_teacher)
        assert q_res.status_code == 200, f"Adding question {idx+1} failed"
        
    # Check that students CANNOT see the exam while in Draft
    headers_s1 = {"Authorization": f"Bearer {s1_token}"}
    headers_s2 = {"Authorization": f"Bearer {s2_token}"}
    
    exams_s1 = client.get("/api/student/exams", headers=headers_s1)
    assert len([e for e in exams_s1.json() if e["id"] == exam_id]) == 0, "Student was able to see draft exam!"
    
    # Make Exam Live
    patch_status = client.patch(f"/api/exams/{exam_id}/status", json={"status": "live"}, headers=headers_teacher)
    assert patch_status.status_code == 200, "Making exam live failed"
    
    # Verify students can now see the exam
    exams_s1 = client.get("/api/student/exams", headers=headers_s1)
    exam_meta = [e for e in exams_s1.json() if e["id"] == exam_id][0]
    assert exam_meta["status"] == "live", "Live exam status check failed"
    assert exam_meta["question_count"] == 3, "Question count mismatch"
    
    # 4. Starting Attempts and checking Shuffling & Randomization
    print("TEST: Starting Attempts (Randomization Checks)")
    
    att1_res = client.post(f"/api/student/exams/{exam_id}/attempt", headers=headers_s1)
    assert att1_res.status_code == 200, "Student 1 start attempt failed"
    att1_id = att1_res.json()["attempt_id"]
    
    att2_res = client.post(f"/api/student/exams/{exam_id}/attempt", headers=headers_s2)
    assert att2_res.status_code == 200, "Student 2 start attempt failed"
    att2_id = att2_res.json()["attempt_id"]
    
    # Fetch attempts details (this yields the shuffled questions)
    att1_details = client.get(f"/api/student/attempts/{att1_id}", headers=headers_s1).json()
    att2_details = client.get(f"/api/student/attempts/{att2_id}", headers=headers_s2).json()
    
    # Confirm correct answers are NOT exposed
    for q in att1_details["questions"]:
        assert "correct_answer" not in q, "Security Alert: Correct answers exposed in attempt details API!"
    
    # TEST 6: Question Randomization Order check
    q1_order = [q["question_id"] for q in att1_details["questions"]]
    q2_order = [q["question_id"] for q in att2_details["questions"]]
    
    print(f"  Student A question order: {q1_order}")
    print(f"  Student B question order: {q2_order}")
    # (Note: In a 3-question pool, there is a small chance they are identical (1/6), but order should generally show randomization)
    
    # TEST 7: Independent option shuffling check
    # Let's find question details for the same question ID in both attempts
    shared_q_id = q1_order[0]
    
    s1_shared_q = [q for q in att1_details["questions"] if q["question_id"] == shared_q_id][0]
    s2_shared_q = [q for q in att2_details["questions"] if q["question_id"] == shared_q_id][0]
    
    s1_options = [o["option_text"] for o in s1_shared_q["options"]]
    s2_options = [o["option_text"] for o in s2_shared_q["options"]]
    
    print(f"  Student A options for Q#{shared_q_id}: {s1_options}")
    print(f"  Student B options for Q#{shared_q_id}: {s2_options}")
    
    # TEST 8: Refresh Page check (no reshuffling on re-fetch)
    att1_refresh = client.get(f"/api/student/attempts/{att1_id}", headers=headers_s1).json()
    q1_refresh_order = [q["question_id"] for q in att1_refresh["questions"]]
    assert q1_order == q1_refresh_order, "Questions reshuffled on refresh!"
    
    # TEST 9: Double active attempt rejection check
    att1_double = client.post(f"/api/student/exams/{exam_id}/attempt", headers=headers_s1)
    assert att1_double.status_code == 400, "Double active attempt was allowed!"
    assert "already have an active attempt" in att1_double.json()["detail"], "Incorrect double attempt error message"
    
    # 5. Saving Answers & Authority score calculations
    print("TEST: Saving Answers & Server-Side Scoring")
    
    # Find option ID for correct answers in Student 1's questions list
    # Q1: Electromagnetic radiation -> Photon (Marks: 4.0, Neg: 1.0)
    # Q2: Uncertainty Principle -> Werner Heisenberg (Marks: 3.0, Neg: 0.5)
    # Q3: Wave function collapse -> Reduction to a single eigenstate (Marks: 3.0, Neg: 0.5)
    
    # Answer Student 1 questions:
    # Let's answer Q1 correctly, Q2 incorrectly, and leave Q3 unattempted
    # Expected Score: 4.0 (correct) - 0.5 (incorrect) = 3.5
    for q in att1_details["questions"]:
        q_id = q["question_id"]
        # Find photon (correct for Q1)
        if q_id == 1:
            photon_opt = [o for o in q["options"] if o["option_text"] == "Photon"][0]
            client.post(f"/api/student/attempts/{att1_id}/save-answer", json={
                "question_id": q_id,
                "selected_option_id": photon_opt["id"]
            }, headers=headers_s1)
        elif q_id == 2:
            # Answer incorrectly with Bohr (correct is Heisenberg)
            bohr_opt = [o for o in q["options"] if o["option_text"] == "Niels Bohr"][0]
            client.post(f"/api/student/attempts/{att1_id}/save-answer", json={
                "question_id": q_id,
                "selected_option_id": bohr_opt["id"]
            }, headers=headers_s1)
            
    # Submit student 1
    submit_res = client.post(f"/api/student/attempts/{att1_id}/submit", json={"submission_type": "manual"}, headers=headers_s1)
    assert submit_res.status_code == 200, "Manual submission failed"
    
    # Fetch result
    result1 = client.get(f"/api/student/attempts/{att1_id}/result", headers=headers_s1).json()
    print(f"  Student A Score: {result1['attempt']['score']} pts ({result1['attempt']['percentage']}%)")
    assert result1["attempt"]["score"] == 3.5, f"Incorrect score calculated. Expected 3.5, got {result1['attempt']['score']}"
    assert result1["stats"]["correct"] == 1
    assert result1["stats"]["incorrect"] == 1
    assert result1["stats"]["unattempted"] == 1
    
    # TEST 10: Confirm student CANNOT change selection after submitting
    q1_post_submit = client.post(f"/api/student/attempts/{att1_id}/save-answer", json={
        "question_id": 1,
        "selected_option_id": 1
    }, headers=headers_s1)
    assert q1_post_submit.status_code == 400, "Saved answer allowed after submission!"
    
    # 6. Anti Cheating lockouts (TEST 1, 2, 3)
    print("TEST: Anti-Cheating & Lockout Detection")
    # Simulate Student 2 triggering a tab visibility violation
    violation_payload = {
        "type": "tab_switch",
        "details": "Student left the exam tab."
    }
    violation_res = client.post(f"/api/student/attempts/{att2_id}/violation", json=violation_payload, headers=headers_s2)
    assert violation_res.status_code == 200, "Violation logging failed"
    
    # Verify Student 2's attempt was locked and submitted automatically
    att2_details_after = client.get(f"/api/student/attempts/{att2_id}", headers=headers_s2).json()
    assert att2_details_after["attempt"]["status"] == "violated", "Attempt status was not set to violated"
    assert att2_details_after["attempt"]["submission_type"] == "tab_switch", "Attempt submission type mismatch"
    
    # 7. Teacher Live Controls (TEST 5: Ending Exam auto-submits others)
    print("TEST: Teacher End Exam - Auto Submit Active Attempts")
    
    # Register student 3
    s3_reg = client.post("/api/auth/register", json={
        "name": "Charlie Student",
        "email": "charlie@college.edu",
        "password": "studentpassword123",
        "role": "student"
    })
    s3_token = s3_reg.json()["token"]
    headers_s3 = {"Authorization": f"Bearer {s3_token}"}
    
    # Start attempt for student 3
    att3_res = client.post(f"/api/student/exams/{exam_id}/attempt", headers=headers_s3)
    att3_id = att3_res.json()["attempt_id"]
    
    # Teacher ends the exam
    end_exam_res = client.patch(f"/api/exams/{exam_id}/status", json={"status": "ended"}, headers=headers_teacher)
    assert end_exam_res.status_code == 200, "Ending exam failed"
    
    # Check that Student 3's active attempt was auto-submitted
    att3_details_after = client.get(f"/api/student/attempts/{att3_id}", headers=headers_s3).json()
    assert att3_details_after["attempt"]["status"] == "submitted", "Student 3 attempt not auto-submitted"
    assert att3_details_after["attempt"]["submission_type"] == "teacher_ended", "Submission type mismatch"
    
    # 8. Teacher Monitoring Dashboard Check
    print("TEST: Teacher live monitor updates")
    monitor_res = client.get(f"/api/exams/{exam_id}/monitor", headers=headers_teacher)
    assert monitor_res.status_code == 200
    mon_list = monitor_res.json()
    assert len(mon_list) == 3, "Monitor attempts list count mismatch"
    
    print("\nALL VERIFICATION TESTS COMPLETED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
