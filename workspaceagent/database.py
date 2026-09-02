import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from Authentication.config import settings


DATABASE_PATH = settings.sqlite_path("workspace_agent.db", Path(__file__).resolve().parent)
RETENTION_SECONDS = 24 * 60 * 60


@contextmanager
def connect():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize():
    with connect() as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
                provider TEXT NOT NULL, model TEXT NOT NULL, created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS workspace_sessions_user ON sessions(user_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user','assistant')),
                content TEXT NOT NULL, trace TEXT, data TEXT, pending_action TEXT,
                pending_status TEXT, created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS workspace_messages_session ON messages(session_id, id);
        """)


def cleanup_expired(now=None):
    cutoff = (now or int(time.time())) - RETENTION_SECONDS
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE updated_at <= ?", (cutoff,))


def list_expiring_sessions(cutoff):
    with connect() as connection:
        rows = connection.execute("SELECT id, user_id FROM sessions WHERE updated_at <= ?", (cutoff,)).fetchall()
    return [dict(row) for row in rows]


def create_session(user_id, provider, model, title="New workspace chat"):
    cleanup_expired()
    now = int(time.time())
    item = {"id": uuid4().hex, "user_id": user_id, "title": title, "provider": provider, "model": model, "created_at": now, "updated_at": now}
    with connect() as connection:
        connection.execute("INSERT INTO sessions VALUES (:id,:user_id,:title,:provider,:model,:created_at,:updated_at)", item)
    return item


def get_session(session_id, user_id):
    cleanup_expired()
    with connect() as connection:
        row = connection.execute("SELECT * FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
    return dict(row) if row else None


def list_sessions(user_id):
    cleanup_expired()
    with connect() as connection:
        rows = connection.execute("SELECT * FROM sessions WHERE user_id=? ORDER BY updated_at DESC, rowid DESC", (user_id,)).fetchall()
    return [dict(row) for row in rows]


def get_messages(session_id, user_id):
    if not get_session(session_id, user_id):
        return []
    with connect() as connection:
        rows = connection.execute("SELECT id,role,content,trace,data,pending_action,pending_status,created_at FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
    return [{
        **dict(row), "trace": json.loads(row["trace"]) if row["trace"] else [],
        "data": json.loads(row["data"]) if row["data"] else None,
        "pending_action": json.loads(row["pending_action"]) if row["pending_action"] else None,
    } for row in rows]


def add_exchange(session_id, user_id, question, result):
    now = int(time.time())
    pending = result.get("pending_action")
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        session = connection.execute("SELECT title FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
        if not session:
            return False
        connection.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES (?,?,?,?)", (session_id, "user", question, now))
        cursor = connection.execute(
            "INSERT INTO messages(session_id,role,content,trace,data,pending_action,pending_status,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (session_id, "assistant", result["message"], json.dumps(result.get("trace", [])), json.dumps(result.get("data")), json.dumps(pending) if pending else None, "pending" if pending else None, now),
        )
        connection.execute(
            "UPDATE sessions SET title=CASE WHEN title='New workspace chat' THEN ? ELSE title END, updated_at=? WHERE id=?",
            (question.replace("\n", " ")[:60], now, session_id),
        )
    return cursor.lastrowid


def claim_action(message_id, user_id):
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT m.pending_action,m.session_id FROM messages m JOIN sessions s ON s.id=m.session_id WHERE m.id=? AND s.user_id=? AND m.pending_status='pending'",
            (message_id, user_id),
        ).fetchone()
        if not row:
            return None
        connection.execute("UPDATE messages SET pending_status='executing' WHERE id=?", (message_id,))
    return {"session_id": row["session_id"], "action": json.loads(row["pending_action"])}


def finish_action(message_id, user_id, content, data):
    with connect() as connection:
        row = connection.execute(
            "SELECT m.session_id FROM messages m JOIN sessions s ON s.id=m.session_id WHERE m.id=? AND s.user_id=?",
            (message_id, user_id),
        ).fetchone()
        if not row:
            return
        connection.execute("UPDATE messages SET pending_status='completed' WHERE id=?", (message_id,))
        connection.execute(
            "INSERT INTO messages(session_id,role,content,trace,data,created_at) VALUES (?,?,?,?,?,?)",
            (row["session_id"], "assistant", content, json.dumps([{"step": "google", "status": "complete", "detail": content}]), json.dumps(data), int(time.time())),
        )


def release_action(message_id, user_id):
    with connect() as connection:
        connection.execute(
            "UPDATE messages SET pending_status='pending' WHERE id=? AND pending_status='executing' "
            "AND session_id IN (SELECT id FROM sessions WHERE user_id=?)",
            (message_id, user_id),
        )


def delete_session(session_id, user_id):
    with connect() as connection:
        cursor = connection.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, user_id))
    return cursor.rowcount > 0


def delete_all_sessions(user_id):
    with connect() as connection:
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
