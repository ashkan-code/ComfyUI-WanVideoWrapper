"""پایگاه داده SQLite برای سیستم پیش‌بینی دکتری سازه"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "questions.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            text        TEXT    NOT NULL,
            options     TEXT,
            correct_answer INTEGER,
            subject     TEXT,
            topic       TEXT,
            subtopic    TEXT,
            difficulty  TEXT,
            year        INTEGER,
            source_file TEXT,
            created_at  TEXT
        );

        -- ماتریس فراوانی موضوع × سال
        CREATE TABLE IF NOT EXISTS topic_year_matrix (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            topic   TEXT,
            subject TEXT,
            year    INTEGER,
            count   INTEGER DEFAULT 1,
            UNIQUE(topic, year)
        );

        -- نتیجه تحلیل الگو
        CREATE TABLE IF NOT EXISTS analyses (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_type TEXT,
            result        TEXT,
            created_at    TEXT
        );

        -- سوالات پیش‌بینی‌شده
        CREATE TABLE IF NOT EXISTS predictions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            questions  TEXT,
            reasoning  TEXT,
            topic_probs TEXT,
            created_at TEXT
        );

        -- تاریخچه تمرین
        CREATE TABLE IF NOT EXISTS practice_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            question_id INTEGER,
            source      TEXT,
            user_answer INTEGER,
            is_correct  INTEGER,
            time_taken  REAL,
            created_at  TEXT
        );
    """)
    conn.commit()
    conn.close()


# ─── سوالات ────────────────────────────────────────────────────────────────────

def add_questions(questions: list[dict]):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().isoformat()
    for q in questions:
        c.execute(
            """INSERT INTO questions
               (text, options, correct_answer, subject, topic, subtopic, difficulty, year, source_file, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
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
                now,
            ),
        )
        # آپدیت ماتریس
        if q.get("topic") and q.get("year"):
            c.execute(
                """INSERT INTO topic_year_matrix (topic, subject, year, count)
                   VALUES (?, ?, ?, 1)
                   ON CONFLICT(topic, year) DO UPDATE SET count = count + 1""",
                (q["topic"], q.get("subject", ""), q["year"]),
            )
    conn.commit()
    conn.close()


def get_all_questions(subject: str = None, topic: str = None, year: int = None) -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    q = "SELECT * FROM questions WHERE 1=1"
    p: list = []
    if subject:
        q += " AND subject=?"; p.append(subject)
    if topic:
        q += " AND topic=?"; p.append(topic)
    if year:
        q += " AND year=?"; p.append(year)
    q += " ORDER BY year, id"
    rows = conn.execute(q, p).fetchall()
    conn.close()
    result = []
    for row in rows:
        d = dict(row)
        d["options"] = json.loads(d["options"]) if d["options"] else []
        result.append(d)
    return result


def get_question_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    return n


def get_years() -> list[int]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT DISTINCT year FROM questions WHERE year IS NOT NULL ORDER BY year").fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_subjects() -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT DISTINCT subject FROM questions WHERE subject!='' ORDER BY subject").fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_topics(subject: str = None) -> list[str]:
    conn = sqlite3.connect(DB_PATH)
    if subject:
        rows = conn.execute("SELECT DISTINCT topic FROM questions WHERE topic!='' AND subject=? ORDER BY topic", (subject,)).fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT topic FROM questions WHERE topic!='' ORDER BY topic").fetchall()
    conn.close()
    return [r[0] for r in rows]


# ─── ماتریس موضوع × سال ────────────────────────────────────────────────────────

def get_topic_year_matrix() -> dict:
    """برمی‌گردونه: {topic: {year: count}}"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT topic, subject, year, count FROM topic_year_matrix ORDER BY year").fetchall()
    conn.close()
    matrix: dict[str, dict] = {}
    for topic, subject, year, count in rows:
        if topic not in matrix:
            matrix[topic] = {"subject": subject, "years": {}}
        matrix[topic]["years"][year] = count
    return matrix


def rebuild_topic_matrix():
    """ماتریس رو از صفر از روی سوالات می‌سازه"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM topic_year_matrix")
    rows = conn.execute(
        "SELECT topic, subject, year, COUNT(*) as cnt FROM questions WHERE topic!='' AND year IS NOT NULL GROUP BY topic, year"
    ).fetchall()
    for topic, subject, year, cnt in rows:
        conn.execute(
            "INSERT OR REPLACE INTO topic_year_matrix (topic, subject, year, count) VALUES (?,?,?,?)",
            (topic, subject, year, cnt),
        )
    conn.commit()
    conn.close()


# ─── تحلیل و پیش‌بینی ──────────────────────────────────────────────────────────

def save_analysis(analysis_type: str, result: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO analyses (analysis_type, result, created_at) VALUES (?,?,?)",
        (analysis_type, json.dumps(result, ensure_ascii=False), datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_latest_analysis(analysis_type: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT result FROM analyses WHERE analysis_type=? ORDER BY created_at DESC LIMIT 1",
        (analysis_type,),
    ).fetchone()
    conn.close()
    return json.loads(row["result"]) if row else None


def save_prediction(questions: list, reasoning: str, topic_probs: dict):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO predictions (questions, reasoning, topic_probs, created_at) VALUES (?,?,?,?)",
        (
            json.dumps(questions, ensure_ascii=False),
            reasoning,
            json.dumps(topic_probs, ensure_ascii=False),
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_latest_prediction() -> tuple[list, str, dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM predictions ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        d = dict(row)
        return json.loads(d["questions"]), d["reasoning"], json.loads(d.get("topic_probs") or "{}")
    return [], "", {}


# ─── تمرین ─────────────────────────────────────────────────────────────────────

def save_practice_result(question_id: int, source: str, user_answer: int, is_correct: bool, time_taken: float):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO practice_sessions (question_id, source, user_answer, is_correct, time_taken, created_at) VALUES (?,?,?,?,?,?)",
        (question_id, source, user_answer, int(is_correct), time_taken, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_practice_stats() -> dict:
    conn = sqlite3.connect(DB_PATH)
    total   = conn.execute("SELECT COUNT(*) FROM practice_sessions").fetchone()[0]
    correct = conn.execute("SELECT COUNT(*) FROM practice_sessions WHERE is_correct=1").fetchone()[0]
    avg_t   = conn.execute("SELECT AVG(time_taken) FROM practice_sessions").fetchone()[0]
    conn.close()
    return {
        "total":    total,
        "correct":  correct,
        "wrong":    total - correct,
        "accuracy": round(correct / total * 100, 1) if total else 0,
        "avg_time": round(avg_t, 1) if avg_t else 0,
    }


def get_weak_topics() -> list[dict]:
    """موضوعاتی که درصد اشتباه بالا دارن"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT q.topic, q.subject,
               COUNT(*) as total,
               SUM(ps.is_correct) as correct
        FROM practice_sessions ps
        JOIN questions q ON q.id = ps.question_id
        WHERE q.topic != ''
        GROUP BY q.topic
        HAVING total >= 3
        ORDER BY (correct * 1.0 / total) ASC
        LIMIT 10
    """).fetchall()
    conn.close()
    return [
        {"topic": r[0], "subject": r[1], "total": r[2], "correct": r[3],
         "accuracy": round(r[3] / r[2] * 100, 1)}
        for r in rows
    ]


def clear_all():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        DELETE FROM questions;
        DELETE FROM topic_year_matrix;
        DELETE FROM analyses;
        DELETE FROM predictions;
        DELETE FROM practice_sessions;
    """)
    conn.commit()
    conn.close()
