import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from Authentication.config import settings


DATABASE_PATH = settings.sqlite_path("basic_rag.db", Path(__file__).resolve().parent)
RETENTION_SECONDS = 24 * 60 * 60
MAX_USER_STORAGE = 5 * 1024 * 1024


class DuplicateDocumentError(ValueError):
    pass


class StorageQuotaError(ValueError):
    pass


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
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL,
                provider TEXT NOT NULL, model TEXT NOT NULL, embedding_model TEXT NOT NULL,
                created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS rag_sessions_user ON sessions(user_id, updated_at DESC);
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                user_id TEXT, content_hash TEXT,
                filename TEXT NOT NULL, content_type TEXT NOT NULL, size INTEGER NOT NULL,
                strategy TEXT NOT NULL, chunk_size INTEGER NOT NULL, overlap INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL, remote_path TEXT NOT NULL, created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS rag_documents_session ON documents(session_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS chunks (
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                position INTEGER NOT NULL, content TEXT NOT NULL,
                PRIMARY KEY(document_id, position)
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
                content TEXT NOT NULL, sources TEXT NOT NULL DEFAULT '[]', trace TEXT, created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS rag_messages_session ON messages(session_id, id);
            """
        )
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)")}
        if "user_id" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN user_id TEXT")
        if "content_hash" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN content_hash TEXT")
        message_columns = {row["name"] for row in connection.execute("PRAGMA table_info(messages)")}
        if "trace" not in message_columns:
            connection.execute("ALTER TABLE messages ADD COLUMN trace TEXT")
        connection.execute(
            "UPDATE documents SET user_id=(SELECT user_id FROM sessions WHERE sessions.id=documents.session_id) WHERE user_id IS NULL"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS rag_documents_user_hash ON documents(user_id, content_hash) WHERE content_hash IS NOT NULL"
        )


def cleanup_expired(database_path=DATABASE_PATH, now=None):
    cutoff = (now or int(time.time())) - RETENTION_SECONDS
    with connect(database_path) as connection:
        connection.execute("DELETE FROM sessions WHERE updated_at <= ?", (cutoff,))


def create_session(user_id, provider, model, embedding_model, database_path=DATABASE_PATH):
    cleanup_expired(database_path)
    now = int(time.time())
    session = {"id": uuid4().hex, "user_id": user_id, "title": "New RAG chat", "provider": provider,
               "model": model, "embedding_model": embedding_model, "created_at": now, "updated_at": now}
    with connect(database_path) as connection:
        connection.execute("INSERT INTO sessions VALUES (:id,:user_id,:title,:provider,:model,:embedding_model,:created_at,:updated_at)", session)
    return session


def get_session(session_id, user_id, database_path=DATABASE_PATH):
    cleanup_expired(database_path)
    with connect(database_path) as connection:
        row = connection.execute("SELECT * FROM sessions WHERE id=? AND user_id=?", (session_id, user_id)).fetchone()
    return dict(row) if row else None


def list_sessions(user_id, database_path=DATABASE_PATH):
    cleanup_expired(database_path)
    with connect(database_path) as connection:
        rows = connection.execute("SELECT * FROM sessions WHERE user_id=? ORDER BY updated_at DESC, rowid DESC", (user_id,)).fetchall()
    return [dict(row) for row in rows]


def list_documents(session_id, user_id, include_chunks=False, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT d.* FROM documents d JOIN sessions s ON s.id=d.session_id WHERE d.session_id=? AND s.user_id=? ORDER BY d.created_at DESC, d.rowid DESC",
            (session_id, user_id),
        ).fetchall()
        documents = [dict(row) for row in rows]
        if include_chunks:
            for document in documents:
                chunks = connection.execute("SELECT position, content FROM chunks WHERE document_id=? ORDER BY position", (document["id"],)).fetchall()
                document["chunks"] = [dict(chunk) for chunk in chunks]
    return documents


def get_document(document_id, user_id, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT d.* FROM documents d JOIN sessions s ON s.id=d.session_id WHERE d.id=? AND s.user_id=?",
            (document_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def find_document_by_hash(user_id, content_hash, database_path=DATABASE_PATH):
    cleanup_expired(database_path)
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM documents WHERE user_id=? AND content_hash=?", (user_id, content_hash)
        ).fetchone()
    return dict(row) if row else None


def document_storage_used(user_id, database_path=DATABASE_PATH):
    cleanup_expired(database_path)
    with connect(database_path) as connection:
        row = connection.execute(
            "SELECT COALESCE(SUM(size), 0) AS total FROM documents WHERE user_id=?", (user_id,)
        ).fetchone()
    return row["total"]


def list_all_documents(user_id, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        rows = connection.execute(
            "SELECT id, chunk_count, remote_path FROM documents WHERE user_id=?", (user_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def delete_all_sessions(user_id, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        connection.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))


def save_document(document_id, session_id, filename, content_type, size, strategy, chunk_size, overlap, remote_path, chunks, database_path=DATABASE_PATH, content_hash=None):
    now = int(time.time())
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM sessions WHERE updated_at <= ?", (now - RETENTION_SECONDS,))
        session = connection.execute("SELECT user_id FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not session:
            return None
        used = connection.execute(
            "SELECT COALESCE(SUM(size), 0) FROM documents WHERE user_id=?", (session["user_id"],)
        ).fetchone()[0]
        if used + size > MAX_USER_STORAGE:
            remaining_mb = max(0, MAX_USER_STORAGE - used) / (1024 * 1024)
            raise StorageQuotaError(f"Only {remaining_mb:.2f} MB of the 5 MB document allowance remains")
        document = {"id": document_id, "session_id": session_id, "user_id": session["user_id"], "content_hash": content_hash,
                "filename": filename, "content_type": content_type,
                "size": size, "strategy": strategy, "chunk_size": chunk_size, "overlap": overlap,
                "chunk_count": len(chunks), "remote_path": remote_path, "created_at": now}
        try:
            connection.execute(
                "INSERT INTO documents(id,session_id,user_id,content_hash,filename,content_type,size,strategy,chunk_size,overlap,chunk_count,remote_path,created_at) VALUES (:id,:session_id,:user_id,:content_hash,:filename,:content_type,:size,:strategy,:chunk_size,:overlap,:chunk_count,:remote_path,:created_at)",
                document,
            )
            connection.executemany("INSERT INTO chunks VALUES (?, ?, ?)", [(document["id"], index, chunk) for index, chunk in enumerate(chunks)])
            connection.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        except sqlite3.IntegrityError as error:
            if content_hash and "documents.user_id, documents.content_hash" in str(error):
                raise DuplicateDocumentError("This document already exists") from error
            raise
    document["chunks"] = [{"position": index, "content": chunk} for index, chunk in enumerate(chunks)]
    return document


def delete_document(document_id, user_id, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        cursor = connection.execute(
            "DELETE FROM documents WHERE id=? AND session_id IN (SELECT id FROM sessions WHERE user_id=?)",
            (document_id, user_id),
        )
    return cursor.rowcount > 0


def get_messages(session_id, user_id, database_path=DATABASE_PATH):
    if not get_session(session_id, user_id, database_path):
        return []
    with connect(database_path) as connection:
        rows = connection.execute("SELECT role, content, sources, trace, created_at FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
    return [{**dict(row), "sources": json.loads(row["sources"]), "trace": json.loads(row["trace"]) if row["trace"] else None} for row in rows]


def add_exchange(session_id, question, answer, sources, database_path=DATABASE_PATH, trace=None):
    now = int(time.time())
    with connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("DELETE FROM sessions WHERE updated_at <= ?", (now - RETENTION_SECONDS,))
        if not connection.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone():
            return False
        connection.executemany(
            "INSERT INTO messages(session_id,role,content,sources,trace,created_at) VALUES (?,?,?,?,?,?)",
            [(session_id, "user", question, "[]", None, now), (session_id, "assistant", answer, json.dumps(sources), json.dumps(trace) if trace else None, now)],
        )
        connection.execute("UPDATE sessions SET title=CASE WHEN title='New RAG chat' THEN ? ELSE title END, updated_at=? WHERE id=?", (question.replace("\n", " ")[:60], now, session_id))
    return True


def delete_session(session_id, user_id, database_path=DATABASE_PATH):
    with connect(database_path) as connection:
        cursor = connection.execute("DELETE FROM sessions WHERE id=? AND user_id=?", (session_id, user_id))
    return cursor.rowcount > 0
