import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "questions.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            options TEXT,
            correct_answer INTEGER,
            subject TEXT,
            topic TEXT,
            subtopic TEXT,
            difficulty TEXT,
            year INTEGER,
            source_file TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_type TEXT,
            result TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            questions TEXT,
            reasoning TEXT,
            created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS practice_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            user_answer INTEGER,
            is_correct INTEGER,
            time_taken REAL,
            created_at TEXT
        );
    """)
    conn.commit()
    conn.close()


def add_questions(questions: list[dict]):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for q in questions:
        c.execute(
            """INSERT INTO questions
               (text, options, correct_answer, subject, topic, subtopic, difficulty, year, source_file, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                q.get("text", ""),
                json.dumps(q.get("options", []), ensure_ascii=False),
                q.get("correct_answer"),
                q.get("subject", ""),
                q.get("topic", ""),
                q.get("subtopic", ""),
                q.get("difficulty", ""),
                q.get("year"),
                q.get("source_file", ""),
                datetime.now().isoformat(),
            ),
        )
    conn.commit()
    conn.close()


def get_all_questions(subject_filter: str = None, topic_filter: str = None) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    query = "SELECT * FROM questions WHERE 1=1"
    params = []
    if subject_filter:
        query += " AND subject = ?"
        params.append(subject_filter)
    if topic_filter:
        query += " AND topic = ?"
        params.append(topic_filter)
    query += " ORDER BY id"
    rows = c.execute(query, params).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        d["options"] = json.loads(d["options"]) if d["options"] else []
        result.append(d)
    return result


def get_question_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    return count


def get_subjects() -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT DISTINCT subject FROM questions WHERE subject != '' ORDER BY subject").fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_topics(subject: str = None) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    if subject:
        rows = conn.execute(
            "SELECT DISTINCT topic FROM questions WHERE topic != '' AND subject = ? ORDER BY topic", (subject,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT topic FROM questions WHERE topic != '' ORDER BY topic").fetchall()
    conn.close()
    return [r[0] for r in rows]


def save_analysis(analysis_type: str, result: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO analyses (analysis_type, result, created_at) VALUES (?, ?, ?)",
        (analysis_type, json.dumps(result, ensure_ascii=False), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_latest_analysis(analysis_type: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM analyses WHERE analysis_type = ? ORDER BY created_at DESC LIMIT 1",
        (analysis_type,),
    ).fetchone()
    conn.close()
    if row:
        return json.loads(dict(row)["result"])
    return None


def save_prediction(questions: list, reasoning: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO predictions (questions, reasoning, created_at) VALUES (?, ?, ?)",
        (json.dumps(questions, ensure_ascii=False), reasoning, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_latest_prediction() -> tuple[list, str]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM predictions ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        d = dict(row)
        return json.loads(d["questions"]), d["reasoning"]
    return [], ""


def save_practice_result(question_id: int, user_answer: int, is_correct: bool, time_taken: float):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO practice_sessions (question_id, user_answer, is_correct, time_taken, created_at) VALUES (?, ?, ?, ?, ?)",
        (question_id, user_answer, int(is_correct), time_taken, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_practice_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM practice_sessions").fetchone()[0]
    correct = conn.execute("SELECT COUNT(*) FROM practice_sessions WHERE is_correct = 1").fetchone()[0]
    avg_time = conn.execute("SELECT AVG(time_taken) FROM practice_sessions").fetchone()[0]
    conn.close()
    return {
        "total": total,
        "correct": correct,
        "wrong": total - correct,
        "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
        "avg_time": round(avg_time, 1) if avg_time else 0,
    }


def clear_all():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("DELETE FROM questions; DELETE FROM analyses; DELETE FROM predictions; DELETE FROM practice_sessions;")
    conn.commit()
    conn.close()
