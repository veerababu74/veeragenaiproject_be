import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from Authentication.config import settings


DATABASE_PATH = settings.sqlite_path("basic_chat.db", Path(__file__).resolve().parent)
RETENTION_SECONDS = 24 * 60 * 60
MAX_MESSAGES = 20


@contextmanager
def connect(database_path=DATABASE_PATH):
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize(database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS messages_session_id ON messages(session_id, id);
            """
        )
        connection.execute(
            """
            UPDATE sessions
            SET expires_at = MAX(
                expires_at,
                COALESCE(
                    (SELECT MAX(created_at) + ? FROM messages WHERE session_id = sessions.id),
                    expires_at
                )
            )
            """,
            (RETENTION_SECONDS,),
        )


def cleanup_expired(database_path=DATABASE_PATH, now=None):
    with connect(database_path) as connection:
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now or int(time.time()),))


def create_session(user_id, provider, model, message, database_path=DATABASE_PATH):
    now = int(time.time())
    session = {
        "id": uuid4().hex,
        "user_id": user_id,
        "title": message.strip().replace("\n", " ")[:60],
        "provider": provider,
        "model": model,
        "created_at": now,
        "expires_at": now + RETENTION_SECONDS,
    }
    with connect(database_path) as connection:
        connection.execute(
            "INSERT INTO sessions VALUES (:id, :user_id, :title, :provider, :model, :created_at, :expires_at)",
            session,
        )
    return session


def get_session(session_id, user_id, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
        ).fetchone()
    return dict(row) if row else None


def list_sessions(user_id, database_path=DATABASE_PATH):
    cleanup_expired(database_path)
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM sessions WHERE user_id = ? ORDER BY expires_at DESC, rowid DESC", (user_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def update_session_title(session_id, message, database_path=DATABASE_PATH):
    title = message.strip().replace("\n", " ")[:60]
    with connect(database_path) as connection:
        connection.execute("UPDATE sessions SET title = ? WHERE id = ?", (title, session_id))
    return title


def get_messages(session_id, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def add_exchange(session_id, user_message, assistant_message, database_path=DATABASE_PATH):
    now = int(time.time())
    expires_at = now + RETENTION_SECONDS
    with connect(database_path) as connection:
        connection.executemany(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            [
                (session_id, "user", user_message, now),
                (session_id, "assistant", assistant_message, now),
            ],
        )
        connection.execute(
            """
            DELETE FROM messages WHERE session_id = ? AND id NOT IN (
                SELECT id FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?
            )
            """,
            (session_id, session_id, MAX_MESSAGES),
        )
        connection.execute(
            "UPDATE sessions SET expires_at = ? WHERE id = ?", (expires_at, session_id)
        )
    return expires_at


def delete_session(session_id, user_id, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        cursor = connection.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
        )
    return cursor.rowcount > 0