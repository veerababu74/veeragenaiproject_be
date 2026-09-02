"""Time-based data retention.

Every app's SQLite `database.py` module knows how to expire its own session rows, but a
session's real footprint often lives elsewhere too: chunk vectors in Pinecone, a knowledge
graph in Neo4j, the original uploaded file in the Hugging Face bucket. Deleting only the
SQLite row leaves that other data orphaned forever, since the row was the only record of
where it lived.

This module is the single place that purges ALL of it, in the right order (external
stores first, SQLite last, so a crash mid-sweep just means we look again next sweep
instead of losing the pointer), for every session across every app that has gone
untouched for more than the retention window. `run_forever()` is started once as a
background task from `main.py`'s lifespan so the sweep happens on a fixed schedule
regardless of whether any user traffic hits the API — the individual `database.py`
modules still call their own `cleanup_expired()` lazily on specific requests too, but
that alone only runs if and when someone happens to hit those endpoints.
"""
import asyncio
import logging
import time

from advancedragapp import database as advanced_rag_database
from basichatapp import database as basic_chat_database
from basicragapp import bucket_storage, database as basic_rag_database, vector_store
from graphragapp import database as graph_rag_database, graph_store
from workspaceagent import database as workspace_agent_database


logger = logging.getLogger("veera.retention")

RUN_INTERVAL_SECONDS = 15 * 60
RETENTION_SECONDS = basic_rag_database.RETENTION_SECONDS


def _purge_rag_store(database_module, cutoff):
    """Remove Pinecone vectors and the bucket file for every document about to expire."""
    for document in database_module.list_documents_expiring(cutoff):
        if document["chunk_count"]:
            try:
                vector_store.delete_document(document["user_id"], document["id"], document["chunk_count"])
            except vector_store.VectorStoreError:
                logger.warning("Retention: could not remove Pinecone vectors for document %s", document["id"])
        if document["remote_path"]:
            try:
                bucket_storage.delete(document["remote_path"])
            except bucket_storage.BucketError:
                logger.warning("Retention: could not remove bucket file for document %s", document["id"])


def _purge_graph_rag(cutoff):
    """Remove the Neo4j graph for every session about to expire, then its bucket files."""
    for session in graph_rag_database.list_expiring_sessions(cutoff):
        try:
            graph_store.delete_session_graph(session["id"], session["user_id"])
        except graph_store.GraphStoreError:
            logger.warning("Retention: could not remove Neo4j graph for session %s", session["id"])
    for document in graph_rag_database.list_documents_expiring(cutoff):
        if document["remote_path"]:
            try:
                bucket_storage.delete(document["remote_path"])
            except bucket_storage.BucketError:
                logger.warning("Retention: could not remove bucket file for document %s", document["id"])


def run_once(now=None):
    """Purge every store for every session inactive past the 24h retention window."""
    now = now or int(time.time())
    cutoff = now - RETENTION_SECONDS

    _purge_rag_store(basic_rag_database, cutoff)
    _purge_rag_store(advanced_rag_database, cutoff)
    _purge_graph_rag(cutoff)

    # External stores are gone; it's now safe to drop the SQLite rows that pointed to them.
    basic_rag_database.cleanup_expired(now=now)
    advanced_rag_database.cleanup_expired(now=now)
    graph_rag_database.cleanup_expired(now=now)
    basic_chat_database.cleanup_expired(now=now)
    workspace_agent_database.cleanup_expired(now=now)
    logger.info("Retention sweep complete")


async def run_forever():
    """Background loop: sweep every RUN_INTERVAL_SECONDS regardless of request traffic."""
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.exception("Retention sweep failed")
        await asyncio.sleep(RUN_INTERVAL_SECONDS)
