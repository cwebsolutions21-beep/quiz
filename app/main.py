import datetime
import json
import random
import time
from typing import List, Dict, Set, Optional, Union
from fastapi import FastAPI, Request, Response, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr

from app.db import init_db, get_db_connection
from app.auth import (
    hash_password,
    verify_password,
    create_token,
    verify_token,
    get_current_user,
    get_current_teacher,
    get_current_student
)

app = FastAPI(title="Secure Online Examination System")

# Enable CORS for local testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    error_messages = []
    for err in exc.errors():
        loc = " -> ".join(str(l) for l in err.get("loc", []))
        msg = err.get("msg", "invalid value")
        error_messages.append(f"{loc}: {msg}")
    friendly_msg = "Validation Error: " + "; ".join(error_messages)
    return JSONResponse(
        status_code=400,
        content={"detail": friendly_msg}
    )

# Initialize database on startup
@app.on_event("startup")
def startup_event():
    init_db()
    conn = get_db_connection()
    user = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if not user:
        cursor = conn.cursor()
        # Seed default teacher
        pwd_hash = hash_password("teacher123")
        cursor.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'teacher')",
            ("Professor Ram", "teacher@college.edu", pwd_hash)
        )
        # Seed default student
        cursor.execute(
            "INSERT INTO users (name, role, roll_no, section, year) VALUES (?, 'student', ?, ?, ?)",
            ("Alice Student", "21CS1001", "A", "3rd Year")
        )
        conn.commit()
    conn.close()

# Real-time WebSocket connection managers
class TeacherConnectionManager:
    def __init__(self):
        # Maps exam_id -> list of active websockets
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, exam_id: int, websocket: WebSocket):
        await websocket.accept()
        if exam_id not in self.active_connections:
            self.active_connections[exam_id] = []
        self.active_connections[exam_id].append(websocket)

    def disconnect(self, exam_id: int, websocket: WebSocket):
        if exam_id in self.active_connections:
            if websocket in self.active_connections[exam_id]:
                self.active_connections[exam_id].remove(websocket)
            if not self.active_connections[exam_id]:
                del self.active_connections[exam_id]

    async def broadcast_to_exam(self, exam_id: int, message: dict):
        if exam_id in self.active_connections:
            for connection in self.active_connections[exam_id]:
                try:
                    await connection.send_json(message)
                except Exception:
                    pass

class StudentConnectionManager:
    def __init__(self):
        # Maps attempt_id -> websocket
        self.active_connections: Dict[int, WebSocket] = {}
        # Keep track of active student attempt IDs to trigger disconnected/active status
        self.active_students: Set[int] = set()

    async def connect(self, attempt_id: int, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[attempt_id] = websocket
        self.active_students.add(attempt_id)

    def disconnect(self, attempt_id: int):
        if attempt_id in self.active_connections:
            del self.active_connections[attempt_id]
        if attempt_id in self.active_students:
            self.active_students.remove(attempt_id)

    async def send_to_student(self, attempt_id: int, message: dict):
        if attempt_id in self.active_connections:
            try:
                await self.active_connections[attempt_id].send_json(message)
                return True
            except Exception:
                return False
        return False

    async def broadcast_to_exam_students(self, exam_id: int, message: dict):
        # Find all active student attempts belonging to this exam
        conn = get_db_connection()
        attempts = conn.execute(
            "SELECT id FROM attempts WHERE exam_id = ? AND status = 'active'", (exam_id,)
        ).fetchall()
        conn.close()
        
        for row in attempts:
            attempt_id = row['id']
            if attempt_id in self.active_connections:
                try:
                    await self.active_connections[attempt_id].send_json(message)
                except Exception:
                    pass

teacher_manager = TeacherConnectionManager()
student_manager = StudentConnectionManager()

# Pydantic schemas
class RegisterSchema(BaseModel):
    name: str
    email: Optional[str] = None
    password: Optional[str] = None
    role: str
    roll_no: Optional[str] = None
    section: Optional[str] = None
    year: Optional[str] = None

class LoginSchema(BaseModel):
    email: Optional[str] = None
    password: Optional[str] = None
    roll_no: Optional[str] = None

class ExamCreateSchema(BaseModel):
    title: str
    description: Optional[str] = ""
    duration: int # in minutes
    total_marks: float
    negative_mark: float = 0.0
    status: str = "draft"
    start_time: Optional[str] = None
    end_time: Optional[str] = None

class OptionCreateSchema(BaseModel):
    option_text: str
    option_image: Optional[str] = None

class QuestionCreateSchema(BaseModel):
    question_text: str
    image: Optional[str] = None
    marks: float = 1.0
    negative_marks: float = 0.0
    correct_answer: str # the text of the correct option
    options: List[Union[str, OptionCreateSchema]]
    explanation: Optional[str] = ""
    topic: Optional[str] = ""
    difficulty: Optional[str] = "medium"

class AnswerSaveSchema(BaseModel):
    question_id: int
    selected_option_id: Optional[int] = None

class SubmitAttemptSchema(BaseModel):
    submission_type: str
    violation_reason: Optional[str] = None

# AUTHENTICATION ROUTING
@app.post("/api/auth/register")
def register(data: RegisterSchema, response: Response):
    if data.role not in ('teacher', 'student'):
        raise HTTPException(status_code=400, detail="Invalid role")
        
    conn = get_db_connection()
    
    if data.role == "teacher":
        if not data.email or not data.password:
            conn.close()
            raise HTTPException(status_code=400, detail="Email and password required for teacher account")
        user_exists = conn.execute("SELECT id FROM users WHERE email = ?", (data.email,)).fetchone()
        if user_exists:
            conn.close()
            raise HTTPException(status_code=400, detail="Email already registered")
            
        pwd_hash = hash_password(data.password)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'teacher')",
                (data.name, data.email, pwd_hash)
            )
            user_id = cursor.lastrowid
            conn.commit()
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
            
        payload = {"user_id": user_id, "email": data.email, "role": "teacher", "name": data.name}
    else:
        if not data.roll_no or not data.section or not data.year:
            conn.close()
            raise HTTPException(status_code=400, detail="Roll number, section, and year required for student account")
        user_exists = conn.execute("SELECT id FROM users WHERE roll_no = ?", (data.roll_no,)).fetchone()
        if user_exists:
            conn.close()
            raise HTTPException(status_code=400, detail="Roll number already registered")
            
        try:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (name, role, roll_no, section, year) VALUES (?, 'student', ?, ?, ?)",
                (data.name, data.roll_no, data.section, data.year)
            )
            user_id = cursor.lastrowid
            conn.commit()
        except Exception as e:
            conn.close()
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
            
        payload = {"user_id": user_id, "roll_no": data.roll_no, "role": "student", "name": data.name}
        
    token = create_token(payload)
    response.set_cookie(key="token", value=token, httponly=True, samesite="lax")
    conn.close()
    return {"status": "success", "user": payload, "token": token}

@app.post("/api/auth/login")
def login(data: LoginSchema, response: Response):
    conn = get_db_connection()
    
    if data.roll_no:
        # Student Login using roll number
        user = conn.execute("SELECT * FROM users WHERE roll_no = ? AND role = 'student'", (data.roll_no,)).fetchone()
        conn.close()
        
        if not user:
            raise HTTPException(status_code=400, detail="Roll number not registered.")
            
        payload = {"user_id": user["id"], "roll_no": user["roll_no"], "role": "student", "name": user["name"]}
    else:
        # Teacher Login using email / password
        if not data.email or not data.password:
            conn.close()
            raise HTTPException(status_code=400, detail="Email and password required")
            
        user = conn.execute("SELECT * FROM users WHERE email = ? AND role = 'teacher'", (data.email,)).fetchone()
        conn.close()
        
        if not user or not verify_password(data.password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="Incorrect email or password")
            
        payload = {"user_id": user["id"], "email": user["email"], "role": "teacher", "name": user["name"]}
        
    token = create_token(payload)
    response.set_cookie(key="token", value=token, httponly=True, samesite="lax")
    return {"status": "success", "user": payload, "token": token}

@app.get("/api/auth/me")
def me(current_user: dict = Depends(get_current_user)):
    return current_user

@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("token")
    return {"status": "success", "message": "Logged out successfully"}


# TEACHER ROUTES
@app.get("/api/exams")
def get_exams(current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    exams = conn.execute(
        "SELECT e.*, (SELECT COUNT(*) FROM questions q WHERE q.exam_id = e.id) as question_count FROM exams e WHERE e.created_by = ? ORDER BY e.id DESC", 
        (current_user["user_id"],)
    ).fetchall()
    conn.close()
    return [dict(e) for e in exams]

@app.post("/api/exams")
def create_exam(data: ExamCreateSchema, current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO exams (title, description, duration, total_marks, negative_mark, status, start_time, end_time, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (data.title, data.description, data.duration, data.total_marks, data.negative_mark, data.status, data.start_time, data.end_time, current_user["user_id"])
    )
    exam_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"status": "success", "exam_id": exam_id}

@app.get("/api/exams/{exam_id}")
def get_exam_details(exam_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    exam = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    conn.close()
    if not exam:
        raise HTTPException(status_code=404, detail="Exam not found")
    return dict(exam)

@app.put("/api/exams/{exam_id}")
def update_exam(exam_id: int, data: ExamCreateSchema, current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    # Check if exam belongs to teacher
    exam = conn.execute("SELECT created_by, status FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam["created_by"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
    if exam["status"] == "live":
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot edit a live exam")
        
    conn.execute(
        """UPDATE exams SET title = ?, description = ?, duration = ?, total_marks = ?, negative_mark = ?, status = ?, start_time = ?, end_time = ?
           WHERE id = ?""",
        (data.title, data.description, data.duration, data.total_marks, data.negative_mark, data.status, data.start_time, data.end_time, exam_id)
    )
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.delete("/api/exams/{exam_id}")
def delete_exam(exam_id: int, current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    exam = conn.execute("SELECT created_by FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam["created_by"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
        
    conn.execute("DELETE FROM exams WHERE id = ?", (exam_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.patch("/api/exams/{exam_id}/status")
async def patch_exam_status(exam_id: int, payload: dict, current_user: dict = Depends(get_current_teacher)):
    new_status = payload.get("status")
    if new_status not in ('draft', 'scheduled', 'live', 'ended'):
        raise HTTPException(status_code=400, detail="Invalid status")
        
    conn = get_db_connection()
    exam = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam["created_by"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
        
    conn.execute("UPDATE exams SET status = ? WHERE id = ?", (new_status, exam_id))
    conn.commit()
    
    # Broadcast status change to student WebSocket if needed
    if new_status == "live":
        # Alert students that a new exam is live
        await student_manager.broadcast_to_exam_students(exam_id, {"event": "exam_started", "exam_id": exam_id})
    elif new_status == "ended":
        # Automatically submit all ACTIVE attempts for this exam
        active_attempts = conn.execute(
            "SELECT id FROM attempts WHERE exam_id = ? AND status = 'active'", (exam_id,)
        ).fetchall()
        
        for row in active_attempts:
            attempt_id = row['id']
            # Submit each attempt automatically as teacher_ended
            await submit_attempt_internal(conn, attempt_id, "teacher_ended", "Teacher ended the exam.")
            # Notify the student frontend
            await student_manager.send_to_student(attempt_id, {"event": "exam_ended_by_teacher"})
        
        conn.commit()
            
        # Alert monitor dashboard
        await teacher_manager.broadcast_to_exam(exam_id, {"event": "refresh"})
        
    conn.close()
    return {"status": "success", "new_status": new_status}


# QUESTIONS MANAGEMENT
@app.get("/api/exams/{exam_id}/questions")
def get_exam_questions(exam_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    questions = conn.execute("SELECT * FROM questions WHERE exam_id = ? ORDER BY id ASC", (exam_id,)).fetchall()
    
    result = []
    for q in questions:
        q_dict = dict(q)
        options = conn.execute("SELECT * FROM question_options WHERE question_id = ?", (q["id"],)).fetchall()
        q_dict["options"] = [dict(opt) for opt in options]
        result.append(q_dict)
        
    conn.close()
    return result

@app.post("/api/exams/{exam_id}/questions")
def add_question(exam_id: int, data: QuestionCreateSchema, current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    exam = conn.execute("SELECT created_by, status FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam["created_by"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
    if exam["status"] == "live":
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot modify questions in a live exam")
        
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO questions (exam_id, question_text, image, marks, negative_marks, correct_answer, explanation, topic, difficulty)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (exam_id, data.question_text, data.image, data.marks, data.negative_marks, data.correct_answer, data.explanation, data.topic, data.difficulty)
    )
    question_id = cursor.lastrowid
    
    for opt in data.options:
        opt_text = opt if isinstance(opt, str) else opt.option_text
        opt_img = None if isinstance(opt, str) else opt.option_image
        cursor.execute(
            "INSERT INTO question_options (question_id, option_text, option_image) VALUES (?, ?, ?)",
            (question_id, opt_text, opt_img)
        )
        
    conn.commit()
    conn.close()
    return {"status": "success", "question_id": question_id}

@app.put("/api/exams/{exam_id}/questions/{question_id}")
def update_question(exam_id: int, question_id: int, data: QuestionCreateSchema, current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    exam = conn.execute("SELECT created_by, status FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam["created_by"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
    if exam["status"] == "live":
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot modify questions in a live exam")
        
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE questions SET question_text = ?, image = ?, marks = ?, negative_marks = ?, correct_answer = ?, explanation = ?, topic = ?, difficulty = ?
           WHERE id = ? AND exam_id = ?""",
        (data.question_text, data.image, data.marks, data.negative_marks, data.correct_answer, data.explanation, data.topic, data.difficulty, question_id, exam_id)
    )
    
    # Recreate options for simplicity
    cursor.execute("DELETE FROM question_options WHERE question_id = ?", (question_id,))
    for opt in data.options:
        opt_text = opt if isinstance(opt, str) else opt.option_text
        opt_img = None if isinstance(opt, str) else opt.option_image
        cursor.execute(
            "INSERT INTO question_options (question_id, option_text, option_image) VALUES (?, ?, ?)",
            (question_id, opt_text, opt_img)
        )
        
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.delete("/api/exams/{exam_id}/questions/{question_id}")
def delete_question(exam_id: int, question_id: int, current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    exam = conn.execute("SELECT created_by, status FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam["created_by"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
    if exam["status"] == "live":
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot modify questions in a live exam")
        
    conn.execute("DELETE FROM questions WHERE id = ? AND exam_id = ?", (question_id, exam_id))
    conn.commit()
    conn.close()
    return {"status": "success"}


# QUESTION BANK ENDPOINTS
@app.get("/api/question-bank")
def get_question_bank(search: Optional[str] = "", topic: Optional[str] = "", difficulty: Optional[str] = "", current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    query = """
        SELECT q.*, e.title as exam_title 
        FROM questions q 
        JOIN exams e ON q.exam_id = e.id 
        WHERE e.created_by = ?
    """
    params = [current_user["user_id"]]
    
    if search:
        query += " AND q.question_text LIKE ?"
        params.append(f"%{search}%")
    if topic:
        query += " AND q.topic = ?"
        params.append(topic)
    if difficulty:
        query += " AND q.difficulty = ?"
        params.append(difficulty)
        
    questions = conn.execute(query, params).fetchall()
    
    result = []
    for q in questions:
        q_dict = dict(q)
        options = conn.execute("SELECT * FROM question_options WHERE question_id = ?", (q["id"],)).fetchall()
        q_dict["options"] = [opt["option_text"] for opt in options]
        result.append(q_dict)
        
    conn.close()
    return result

@app.get("/api/question-bank/export")
def export_question_bank(current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    questions = conn.execute(
        "SELECT q.* FROM questions q JOIN exams e ON q.exam_id = e.id WHERE e.created_by = ?", (current_user["user_id"],)
    ).fetchall()
    
    result = []
    for q in questions:
        q_dict = dict(q)
        # remove internal exam IDs
        del q_dict["id"]
        del q_dict["exam_id"]
        options = conn.execute("SELECT option_text FROM question_options WHERE question_id = ?", (q["id"],)).fetchall()
        q_dict["options"] = [opt["option_text"] for opt in options]
        result.append(q_dict)
        
    conn.close()
    return result

@app.post("/api/question-bank/import")
def import_question_bank(payload: dict, current_user: dict = Depends(get_current_teacher)):
    exam_id = payload.get("exam_id")
    questions_list = payload.get("questions")
    if not exam_id or not questions_list:
        raise HTTPException(status_code=400, detail="Missing exam_id or questions list")
        
    conn = get_db_connection()
    exam = conn.execute("SELECT created_by, status FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam["created_by"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
    if exam["status"] == "live":
        conn.close()
        raise HTTPException(status_code=400, detail="Cannot import into a live exam")
        
    cursor = conn.cursor()
    for q in questions_list:
        cursor.execute(
            """INSERT INTO questions (exam_id, question_text, image, marks, negative_marks, correct_answer, explanation, topic, difficulty)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (exam_id, q["question_text"], q.get("image"), q.get("marks", 1.0), q.get("negative_marks", 0.0), q["correct_answer"], q.get("explanation"), q.get("topic"), q.get("difficulty", "medium"))
        )
        q_id = cursor.lastrowid
        for opt in q["options"]:
            cursor.execute("INSERT INTO question_options (question_id, option_text) VALUES (?, ?)", (q_id, opt))
            
    conn.commit()
    conn.close()
    return {"status": "success", "count": len(questions_list)}


# STUDENT ROUTES
@app.get("/api/student/exams")
def get_student_exams(current_user: dict = Depends(get_current_student)):
    conn = get_db_connection()
    # Find all active exams + student attempts on those exams
    exams = conn.execute("""
        SELECT e.*, u.name as teacher_name,
               a.id as attempt_id, a.status as attempt_status, a.score as attempt_score, a.submitted_at as attempt_submitted_at
        FROM exams e
        JOIN users u ON e.created_by = u.id
        LEFT JOIN attempts a ON a.exam_id = e.id AND a.student_id = ?
        WHERE e.status IN ('live', 'ended')
        ORDER BY e.id DESC
    """, (current_user["user_id"],)).fetchall()
    
    result = []
    for e in exams:
        d = dict(e)
        # Check count of questions
        count = conn.execute("SELECT COUNT(*) as cnt FROM questions WHERE exam_id = ?", (e["id"],)).fetchone()
        d["question_count"] = count["cnt"]
        result.append(d)
        
    conn.close()
    return result

@app.post("/api/student/exams/{exam_id}/attempt")
async def start_exam_attempt(exam_id: int, current_user: dict = Depends(get_current_student)):
    conn = get_db_connection()
    
    # 1. Verify exam is Live
    exam = conn.execute("SELECT * FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam:
        conn.close()
        raise HTTPException(status_code=404, detail="Exam not found")
    if exam["status"] != "live":
        conn.close()
        raise HTTPException(status_code=400, detail="This exam is not active or has ended.")
        
    # 2. Check if student already has an attempt
    existing_attempt = conn.execute(
        "SELECT id, status FROM attempts WHERE exam_id = ? AND student_id = ?",
        (exam_id, current_user["user_id"])
    ).fetchone()
    
    if existing_attempt:
        conn.close()
        raise HTTPException(status_code=400, detail="You already have an active attempt for this examination.")
        
    # 3. Create attempt
    now = datetime.datetime.utcnow()
    duration_delta = datetime.timedelta(minutes=exam["duration"])
    expires_at = now + duration_delta
    
    started_at_str = now.isoformat() + "Z"
    expires_at_str = expires_at.isoformat() + "Z"
    
    cursor = conn.cursor()
    try:
        cursor.execute(
            """INSERT INTO attempts (exam_id, student_id, started_at, expires_at, status)
               VALUES (?, ?, ?, ?, 'active')""",
            (exam_id, current_user["user_id"], started_at_str, expires_at_str)
        )
        attempt_id = cursor.lastrowid
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=400, detail="Attempt creation failed. You might already have started this exam.")
        
    # 4. RANDOMIZATION - VERY IMPORTANT
    # Fetch questions
    questions = conn.execute("SELECT id FROM questions WHERE exam_id = ?", (exam_id,)).fetchall()
    question_ids = [q["id"] for q in questions]
    
    # Shuffle question list
    random.shuffle(question_ids)
    
    # Insert randomized question ordering and randomize options mapping
    for index, q_id in enumerate(question_ids):
        cursor.execute(
            "INSERT INTO attempt_questions (attempt_id, question_id, question_order) VALUES (?, ?, ?)",
            (attempt_id, q_id, index)
        )
        attempt_q_id = cursor.lastrowid
        
        # Get options for this question
        options = conn.execute("SELECT id FROM question_options WHERE question_id = ?", (q_id,)).fetchall()
        option_ids = [o["id"] for o in options]
        
        # Shuffle option list
        random.shuffle(option_ids)
        
        for o_index, o_id in enumerate(option_ids):
            cursor.execute(
                """INSERT INTO attempt_options (attempt_question_id, original_option_id, displayed_order)
                   VALUES (?, ?, ?)""",
                (attempt_q_id, o_id, o_index)
            )
            
    conn.commit()
    
    # Notify teachers about a new active attempt
    await teacher_manager.broadcast_to_exam(exam_id, {
        "event": "student_status_change",
        "student_id": current_user["user_id"],
        "name": current_user["name"],
        "status": "Active"
    })
    
    conn.close()
    return {"status": "success", "attempt_id": attempt_id, "expires_at": expires_at_str}

@app.get("/api/student/attempts/{attempt_id}")
def get_attempt_details(attempt_id: int, current_user: dict = Depends(get_current_student)):
    conn = get_db_connection()
    attempt = conn.execute(
        "SELECT a.*, e.title as exam_title, e.duration as exam_duration FROM attempts a JOIN exams e ON a.exam_id = e.id WHERE a.id = ?",
        (attempt_id,)
    ).fetchone()
    
    if not attempt:
        conn.close()
        raise HTTPException(status_code=404, detail="Attempt not found")
        
    if attempt["student_id"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
        
    # Check if expired based on server time
    now_utc = datetime.datetime.utcnow()
    expires_at_dt = datetime.datetime.fromisoformat(attempt["expires_at"].rstrip("Z"))
    
    # Authoritative server validation of timer
    if attempt["status"] == "active" and now_utc > expires_at_dt:
        # Submit automatically as time expired
        conn.close()
        # Force submit from backend immediately!
        import asyncio
        loop = asyncio.get_event_loop()
        # Call submit_attempt_internal synchronously by reusing DB connection or opening new
        conn2 = get_db_connection()
        loop.run_until_complete(submit_attempt_internal(conn2, attempt_id, "time_expired", "Time expired."))
        conn2.close()
        
        # Reload attempt
        conn = get_db_connection()
        attempt = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        
    if attempt["status"] != "active":
        conn.close()
        return {
            "status": "success",
            "attempt": dict(attempt),
            "questions": []
        }
        
    # Fetch questions in the randomized order saved in db
    db_questions = conn.execute("""
        SELECT aq.id as attempt_q_id, q.id as question_id, q.question_text, q.image, q.marks
        FROM attempt_questions aq
        JOIN questions q ON aq.question_id = q.id
        WHERE aq.attempt_id = ?
        ORDER BY aq.question_order ASC
    """, (attempt_id,)).fetchall()
    
    questions = []
    for q in db_questions:
        q_dict = dict(q)
        
        # Fetch options in randomized order
        db_options = conn.execute("""
            SELECT ao.original_option_id as id, qo.option_text, qo.option_image
            FROM attempt_options ao
            JOIN question_options qo ON ao.original_option_id = qo.id
            WHERE ao.attempt_question_id = ?
            ORDER BY ao.displayed_order ASC
        """, (q["attempt_q_id"],)).fetchall()
        
        q_dict["options"] = [dict(opt) for opt in db_options]
        
        # Fetch if student has already answered this question
        ans = conn.execute(
            "SELECT selected_option_id FROM answers WHERE attempt_id = ? AND question_id = ?",
            (attempt_id, q["question_id"])
        ).fetchone()
        q_dict["selected_option_id"] = ans["selected_option_id"] if ans else None
        
        questions.append(q_dict)
        
    # Remaining seconds
    remaining_sec = max(0, int((expires_at_dt - now_utc).total_seconds()))
    
    conn.close()
    return {
        "status": "success",
        "attempt": dict(attempt),
        "questions": questions,
        "remaining_seconds": remaining_sec
    }

@app.post("/api/student/attempts/{attempt_id}/save-answer")
async def save_answer(attempt_id: int, data: AnswerSaveSchema, current_user: dict = Depends(get_current_student)):
    conn = get_db_connection()
    attempt = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt:
        conn.close()
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt["student_id"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
    if attempt["status"] != "active":
        conn.close()
        raise HTTPException(status_code=400, detail="This exam has already been submitted or locked.")
        
    # Check server time expiration
    now_utc = datetime.datetime.utcnow()
    expires_at_dt = datetime.datetime.fromisoformat(attempt["expires_at"].rstrip("Z"))
    if now_utc > expires_at_dt:
        await submit_attempt_internal(conn, attempt_id, "time_expired", "Time expired.")
        conn.commit()
        conn.close()
        raise HTTPException(status_code=400, detail="Time expired. Exam submitted.")
        
    # Verify selected option exists and belongs to the question
    if data.selected_option_id is not None:
        opt = conn.execute(
            "SELECT id FROM question_options WHERE id = ? AND question_id = ?",
            (data.selected_option_id, data.question_id)
        ).fetchone()
        if not opt:
            conn.close()
            raise HTTPException(status_code=400, detail="Invalid option ID")
            
    # Save the answer
    now_str = now_utc.isoformat() + "Z"
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO answers (attempt_id, question_id, selected_option_id, answered_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(attempt_id, question_id) DO UPDATE SET
           selected_option_id = EXCLUDED.selected_option_id,
           answered_at = EXCLUDED.answered_at""",
        (attempt_id, data.question_id, data.selected_option_id, now_str)
    )
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/student/attempts/{attempt_id}/submit")
async def submit_attempt(attempt_id: int, data: SubmitAttemptSchema, current_user: dict = Depends(get_current_student)):
    conn = get_db_connection()
    attempt = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt:
        conn.close()
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt["student_id"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
    if attempt["status"] != "active":
        # Idempotent return
        score = conn.execute("SELECT score, percentage, status FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
        conn.close()
        return {"status": "success", "message": "Already submitted", "score": score["score"]}
        
    await submit_attempt_internal(conn, attempt_id, data.submission_type, data.violation_reason)
    conn.commit()
    conn.close()
    return {"status": "success"}

@app.post("/api/student/attempts/{attempt_id}/violation")
async def log_violation(attempt_id: int, payload: dict, current_user: dict = Depends(get_current_student)):
    v_type = payload.get("type")
    details = payload.get("details", "")
    if v_type not in ('tab_switch', 'page_hidden', 'fullscreen_exit'):
        raise HTTPException(status_code=400, detail="Invalid violation type")
        
    conn = get_db_connection()
    attempt = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt:
        conn.close()
        raise HTTPException(status_code=404, detail="Attempt not found")
    if attempt["student_id"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
        
    now_str = datetime.datetime.utcnow().isoformat() + "Z"
    cursor = conn.cursor()
    
    # 1. Log in violations table
    cursor.execute(
        "INSERT INTO violations (attempt_id, type, timestamp, details) VALUES (?, ?, ?, ?)",
        (attempt_id, v_type, now_str, details)
    )
    
    # 2. AUTO-SUBMIT IMMEDIATELY
    # Map violation type to submission type
    sub_type = "tab_switch"
    if v_type == "page_hidden":
        sub_type = "page_hidden"
    elif v_type == "fullscreen_exit":
        sub_type = "fullscreen_exit"
        
    await submit_attempt_internal(conn, attempt_id, sub_type, f"Exam automatically submitted due to violation: {v_type}. {details}")
    
    conn.commit()
    
    # Notify teacher monitoring web sockets about this violation
    await teacher_manager.broadcast_to_exam(attempt["exam_id"], {"event": "refresh"})
    
    conn.close()
    return {"status": "success", "message": f"Violation logged: {v_type}. Exam auto-submitted."}

# SHARED SUBMIT LOGIC (CALCULATES SCORE)
async def submit_attempt_internal(conn, attempt_id: int, submission_type: str, violation_reason: str = None):
    # Check attempt details
    attempt = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt:
        return
        
    exam = conn.execute("SELECT * FROM exams WHERE id = ?", (attempt["exam_id"],)).fetchone()
    questions = conn.execute("SELECT * FROM questions WHERE exam_id = ?", (attempt["exam_id"],)).fetchall()
    
    # Calculate score
    total_marks = 0.0
    obtained_score = 0.0
    
    # Answers lookup
    answers = conn.execute("SELECT * FROM answers WHERE attempt_id = ?", (attempt_id,)).fetchall()
    ans_map = {ans["question_id"]: ans["selected_option_id"] for ans in answers}
    
    for q in questions:
        q_marks = q["marks"]
        q_neg = q["negative_marks"] if q["negative_marks"] else 0.0
        
        # Get options for question to compare selected
        options = conn.execute("SELECT * FROM question_options WHERE question_id = ?", (q["id"],)).fetchall()
        opt_map = {o["id"]: o["option_text"] for o in options}
        
        selected_option_id = ans_map.get(q["id"])
        
        if selected_option_id is not None:
            selected_text = opt_map.get(selected_option_id)
            if selected_text == q["correct_answer"]:
                obtained_score += q_marks
            else:
                obtained_score -= q_neg
                
    # final score check
    obtained_score = round(obtained_score, 2)
    max_exam_marks = exam["total_marks"] if exam["total_marks"] > 0 else 100.0
    percentage = round((obtained_score / max_exam_marks) * 100, 2)
    
    now_str = datetime.datetime.utcnow().isoformat() + "Z"
    status_str = "violated" if submission_type in ('tab_switch', 'page_hidden', 'fullscreen_exit') else "submitted"
    
    conn.execute(
        """UPDATE attempts SET
           submitted_at = ?,
           status = ?,
           submission_type = ?,
           violation_reason = ?,
           score = ?,
           percentage = ?
           WHERE id = ?""",
        (now_str, status_str, submission_type, violation_reason, obtained_score, percentage, attempt_id)
    )
    
    # Notify monitoring dashboard
    await teacher_manager.broadcast_to_exam(attempt["exam_id"], {
        "event": "student_status_change",
        "student_id": attempt["student_id"],
        "status": status_str,
        "score": obtained_score,
        "violation": violation_reason if status_str == "violated" else None
    })

@app.get("/api/student/attempts/{attempt_id}/result")
def get_attempt_result(attempt_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    attempt = conn.execute(
        "SELECT a.*, e.title as exam_title, e.description as exam_desc, e.total_marks as exam_total_marks, e.negative_mark as exam_negative_mark "
        "FROM attempts a JOIN exams e ON a.exam_id = e.id WHERE a.id = ?", (attempt_id,)
    ).fetchone()
    
    if not attempt:
        conn.close()
        raise HTTPException(status_code=404, detail="Attempt not found")
        
    # Check permissions (either the student who attempted it, or the teacher who created the exam)
    is_teacher = current_user.get("role") == "teacher"
    if not is_teacher and attempt["student_id"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
        
    # Fetch student details
    student = conn.execute("SELECT name, email FROM users WHERE id = ?", (attempt["student_id"],)).fetchone()
    
    # Fetch questions with answers
    questions = conn.execute("SELECT * FROM questions WHERE exam_id = ? ORDER BY id ASC", (attempt["exam_id"],)).fetchall()
    
    # Student answers
    answers = conn.execute("SELECT * FROM answers WHERE attempt_id = ?", (attempt_id,)).fetchall()
    ans_map = {ans["question_id"]: ans["selected_option_id"] for ans in answers}
    
    # Violations count
    v_count = conn.execute("SELECT COUNT(*) as cnt FROM violations WHERE attempt_id = ?", (attempt_id,)).fetchone()
    
    q_results = []
    total_questions = len(questions)
    correct_count = 0
    incorrect_count = 0
    unattempted_count = 0
    
    for q in questions:
        q_dict = dict(q)
        options = conn.execute("SELECT * FROM question_options WHERE question_id = ?", (q["id"],)).fetchall()
        q_dict["options"] = [dict(opt) for opt in options]
        
        selected_opt_id = ans_map.get(q["id"])
        q_dict["selected_option_id"] = selected_opt_id
        
        # Check correct / wrong / unattempted
        selected_text = None
        for o in options:
            if o["id"] == selected_opt_id:
                selected_text = o["option_text"]
                break
                
        if selected_opt_id is None:
            q_dict["result_status"] = "unattempted"
            unattempted_count += 1
        elif selected_text == q["correct_answer"]:
            q_dict["result_status"] = "correct"
            correct_count += 1
        else:
            q_dict["result_status"] = "incorrect"
            incorrect_count += 1
            
        q_results.append(q_dict)
        
    # Calculate time taken
    started = datetime.datetime.fromisoformat(attempt["started_at"].rstrip("Z"))
    ended = datetime.datetime.fromisoformat(attempt["submitted_at"].rstrip("Z")) if attempt["submitted_at"] else started
    time_taken_sec = int((ended - started).total_seconds())
    time_taken_str = f"{time_taken_sec // 60}m {time_taken_sec % 60}s"
    
    conn.close()
    return {
        "status": "success",
        "attempt": dict(attempt),
        "student": dict(student) if student else None,
        "questions": q_results,
        "stats": {
            "total": total_questions,
            "attempted": correct_count + incorrect_count,
            "unattempted": unattempted_count,
            "correct": correct_count,
            "incorrect": incorrect_count,
            "time_taken": time_taken_str,
            "violations_count": v_count["cnt"]
        }
    }


# LIVE STUDENT MONITORING
@app.get("/api/exams/{exam_id}/monitor")
def monitor_exam_attempts(exam_id: int, current_user: dict = Depends(get_current_teacher)):
    conn = get_db_connection()
    # Check if exam belongs to teacher
    exam = conn.execute("SELECT created_by FROM exams WHERE id = ?", (exam_id,)).fetchone()
    if not exam or exam["created_by"] != current_user["user_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Forbidden")
        
    # Fetch attempts
    attempts = conn.execute("""
        SELECT a.id as attempt_id, a.started_at, a.submitted_at, a.status, a.submission_type, a.violation_reason, a.score,
               u.id as student_id, u.name as student_name, u.email as student_email, u.roll_no, u.section, u.year
        FROM attempts a
        JOIN users u ON a.student_id = u.id
        WHERE a.exam_id = ?
        ORDER BY u.name ASC
    """, (exam_id,)).fetchall()
    
    result = []
    for row in attempts:
        d = dict(row)
        # Check if student is currently connected in active_students set
        is_online = row["attempt_id"] in student_manager.active_students
        if row["status"] == "active":
            d["live_status"] = "Active" if is_online else "Disconnected"
        else:
            d["live_status"] = "Submitted" if row["status"] == "submitted" else "Auto Submitted"
            
        result.append(d)
        
    conn.close()
    return result


# WEBSOCKET CONNECTIONS FOR REAL-TIME UPDATES
@app.websocket("/ws/teacher/{exam_id}")
async def websocket_teacher(websocket: WebSocket, exam_id: int, token: Optional[str] = None):
    # Verify token
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    payload = verify_token(token)
    if not payload or payload.get("role") != "teacher":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    await teacher_manager.connect(exam_id, websocket)
    try:
        while True:
            # We just wait to keep the connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        teacher_manager.disconnect(exam_id, websocket)
    except Exception:
        teacher_manager.disconnect(exam_id, websocket)

@app.websocket("/ws/student/{attempt_id}")
async def websocket_student(websocket: WebSocket, attempt_id: int, token: Optional[str] = None):
    # Verify token
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    payload = verify_token(token)
    if not payload or payload.get("role") != "student":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    conn = get_db_connection()
    attempt = conn.execute("SELECT exam_id, student_id FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if not attempt or attempt["student_id"] != payload["user_id"]:
        conn.close()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
        
    exam_id = attempt["exam_id"]
    conn.close()
    
    await student_manager.connect(attempt_id, websocket)
    
    # Notify teacher monitor dashboard that student is online
    await teacher_manager.broadcast_to_exam(exam_id, {"event": "refresh"})
    
    try:
        while True:
            # Keep alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        student_manager.disconnect(attempt_id)
        # Notify teacher monitor dashboard that student has gone offline (Disconnected)
        await teacher_manager.broadcast_to_exam(exam_id, {"event": "refresh"})
    except Exception:
        student_manager.disconnect(attempt_id)
        await teacher_manager.broadcast_to_exam(exam_id, {"event": "refresh"})


# SERVING THE SPA FRONTEND
# Default index.html router
@app.get("/")
def serve_index():
    return FileResponse("static/index.html")

# Serve specific static files dynamically if static directory mounted
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass
