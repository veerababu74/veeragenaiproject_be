import logging

from advancedragapp import database as advanced_rag_database
from basichatapp import database as basic_chat_database
from basicragapp import bucket_storage, database as basic_rag_database, vector_store
from graphragapp import database as graph_rag_database, graph_store
from workspaceagent import database as workspace_agent_database
from workspaceagent.oauth import GoogleConnectionError, decrypt_token, revoke


logger = logging.getLogger("veera.account_deletion")


def _purge_rag_documents(database_module, user_id):
    for document in database_module.list_all_documents(user_id):
        try:
            vector_store.delete_document(user_id, document["id"], document["chunk_count"])
        except vector_store.VectorStoreError:
            logger.warning("Could not remove vectors for document %s during account deletion", document["id"])
        try:
            bucket_storage.delete(document["remote_path"])
        except bucket_storage.BucketError:
            logger.warning("Could not remove stored file for document %s during account deletion", document["id"])


def _purge_graph_rag(user_id):
    for session in graph_rag_database.list_sessions(user_id):
        try:
            graph_store.delete_session_graph(session["id"])
        except graph_store.GraphStoreError:
            logger.warning("Could not remove the Neo4j graph for session %s during account deletion", session["id"])
    for document in graph_rag_database.list_all_documents(user_id):
        try:
            bucket_storage.delete(document["remote_path"])
        except bucket_storage.BucketError:
            logger.warning("Could not remove stored file for document %s during account deletion", document["id"])


def delete_user_workspace_data(user, jwt_secret):
    user_id = str(user["_id"])
    _purge_rag_documents(basic_rag_database, user_id)
    _purge_rag_documents(advanced_rag_database, user_id)
    _purge_graph_rag(user_id)
    basic_chat_database.delete_all_sessions(user_id)
    basic_rag_database.delete_all_sessions(user_id)
    advanced_rag_database.delete_all_sessions(user_id)
    graph_rag_database.delete_all_sessions(user_id)
    workspace_agent_database.delete_all_sessions(user_id)
    connection = user.get("google_workspace")
    if connection and connection.get("refresh_token"):
        try:
            revoke(decrypt_token(connection["refresh_token"], jwt_secret))
        except GoogleConnectionError:
            logger.warning("Could not revoke Google Workspace access during account deletion")
