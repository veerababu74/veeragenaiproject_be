from pathlib import Path

from Authentication.config import settings
from basicragapp import database as base


DATABASE_PATH = settings.sqlite_path("advanced_rag.db", Path(__file__).resolve().parent)
DuplicateDocumentError = base.DuplicateDocumentError
StorageQuotaError = base.StorageQuotaError
MAX_USER_STORAGE = base.MAX_USER_STORAGE


def initialize():
    base.initialize(DATABASE_PATH)


def create_session(user_id, provider, model, embedding_model):
    return base.create_session(user_id, provider, model, embedding_model, DATABASE_PATH)


def get_session(session_id, user_id):
    return base.get_session(session_id, user_id, DATABASE_PATH)


def list_sessions(user_id):
    return base.list_sessions(user_id, DATABASE_PATH)


def list_documents(session_id, user_id, include_chunks=False):
    return base.list_documents(session_id, user_id, include_chunks, DATABASE_PATH)


def get_document(document_id, user_id):
    return base.get_document(document_id, user_id, DATABASE_PATH)


def find_document_by_hash(user_id, content_hash):
    return base.find_document_by_hash(user_id, content_hash, DATABASE_PATH)


def document_storage_used(user_id):
    return base.document_storage_used(user_id, DATABASE_PATH)


def list_all_documents(user_id):
    return base.list_all_documents(user_id, DATABASE_PATH)


def delete_all_sessions(user_id):
    return base.delete_all_sessions(user_id, DATABASE_PATH)


def save_document(document_id, session_id, filename, content_type, size, strategy, chunk_size, overlap, remote_path, chunks, content_hash):
    return base.save_document(
        document_id, session_id, filename, content_type, size, strategy, chunk_size,
        overlap, remote_path, chunks, DATABASE_PATH, content_hash,
    )


def delete_document(document_id, user_id):
    return base.delete_document(document_id, user_id, DATABASE_PATH)


def get_messages(session_id, user_id):
    return base.get_messages(session_id, user_id, DATABASE_PATH)


def add_exchange(session_id, question, answer, sources, trace):
    return base.add_exchange(session_id, question, answer, sources, DATABASE_PATH, trace)


def delete_session(session_id, user_id):
    return base.delete_session(session_id, user_id, DATABASE_PATH)
