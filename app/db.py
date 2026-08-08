import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "quiz.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Users table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE, -- Nullable for students
        password_hash TEXT, -- Nullable for students
        role TEXT NOT NULL CHECK(role IN ('teacher', 'student')),
        roll_no TEXT UNIQUE,
        section TEXT,
        year TEXT
    );
    """)
    
    # Run quick migrations for existing databases
    for col in [("roll_no", "TEXT"), ("section", "TEXT"), ("year", "TEXT")]:
        try:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col[0]} {col[1]}")
        except Exception:
            pass
            
    # Also ensure email is nullable (SQLite allows altering table or it is already handled)
    
    # Exams table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS exams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        duration INTEGER NOT NULL, -- in minutes
        total_marks REAL NOT NULL,
        negative_mark REAL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'scheduled', 'live', 'ended')),
        start_time TEXT,
        end_time TEXT,
        created_by INTEGER NOT NULL,
        FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE CASCADE
    );
    """)
    
    # Questions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        question_text TEXT NOT NULL,
        image TEXT, -- Base64 or local filepath
        marks REAL NOT NULL DEFAULT 1.0,
        negative_marks REAL NOT NULL DEFAULT 0.0,
        correct_answer TEXT NOT NULL,
        explanation TEXT,
        topic TEXT,
        difficulty TEXT CHECK(difficulty IN ('easy', 'medium', 'hard')),
        FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE
    );
    """)
    
    # Question Options table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS question_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        question_id INTEGER NOT NULL,
        option_text TEXT NOT NULL,
        option_image TEXT,
        FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
    );
    """)
    
    # Run migration for option_image column
    try:
        cursor.execute("ALTER TABLE question_options ADD COLUMN option_image TEXT")
    except Exception:
        pass
    
    # Attempts table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        exam_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        submitted_at TEXT,
        status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'submitted', 'violated')),
        submission_type TEXT CHECK(submission_type IN ('manual', 'time_expired', 'tab_switch', 'page_hidden', 'fullscreen_exit', 'teacher_ended')),
        violation_reason TEXT,
        score REAL,
        percentage REAL,
        FOREIGN KEY (exam_id) REFERENCES exams(id) ON DELETE CASCADE,
        FOREIGN KEY (student_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(exam_id, student_id) -- Ensures only one attempt record per student per exam
    );
    """)
    
    # Attempt Questions mapping (to persist randomized question order)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attempt_questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        question_order INTEGER NOT NULL,
        FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
        FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE
    );
    """)
    
    # Attempt Options mapping (to persist randomized option order)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attempt_options (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_question_id INTEGER NOT NULL,
        original_option_id INTEGER NOT NULL,
        displayed_order INTEGER NOT NULL,
        FOREIGN KEY (attempt_question_id) REFERENCES attempt_questions(id) ON DELETE CASCADE,
        FOREIGN KEY (original_option_id) REFERENCES question_options(id) ON DELETE CASCADE
    );
    """)
    
    # Student Answers table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS answers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        question_id INTEGER NOT NULL,
        selected_option_id INTEGER,
        answered_at TEXT,
        FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE,
        FOREIGN KEY (question_id) REFERENCES questions(id) ON DELETE CASCADE,
        FOREIGN KEY (selected_option_id) REFERENCES question_options(id) ON DELETE SET NULL,
        UNIQUE(attempt_id, question_id)
    );
    """)
    
    # Violations table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS violations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('tab_switch', 'page_hidden', 'fullscreen_exit')),
        timestamp TEXT NOT NULL,
        details TEXT,
        FOREIGN KEY (attempt_id) REFERENCES attempts(id) ON DELETE CASCADE
    );
    """)
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")
