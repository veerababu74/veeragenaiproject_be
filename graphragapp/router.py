import asyncio
import hashlib
import json
import logging
from pathlib import Path
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from Authentication.database import users
from Authentication.security import current_user_id, has_project_access
from basichatapp.providers import ProviderError
from basicragapp import bucket_storage
from basicragapp.documents import DocumentError, extract_text
from basicragapp.embeddings import EmbeddingError
from basicragapp.router import _check_storage_quota, _storage_payload

from . import database, graph_store, pipeline
from .models import GraphChatRequest, SessionCreateRequest


PROJECT_ID = "graph-rag"
MAX_FILE_SIZE = 3 * 1024 * 1024
router = APIRouter(prefix="/graph-rag", tags=["Graph RAG"])
logger = logging.getLogger("veera.graph_rag")

QUERY_TEMPLATES = {
    "all-entities": {
        "label": "List every entity in this session",
        "description": "Reads all Entity nodes created from your documents, newest first.",
        "cypher": "MATCH (e:Entity {session_id: $session_id})\nRETURN e.name AS name, e.type AS type, e.description AS description\nORDER BY name\nLIMIT 100",
    },
    "all-relationships": {
        "label": "List every relationship",
        "description": "Reads each RELATES edge as a source, type, target triple.",
        "cypher": "MATCH (a:Entity {session_id: $session_id})-[r:RELATES]->(b:Entity {session_id: $session_id})\nRETURN a.name AS source, r.type AS relationship, b.name AS target, r.description AS description\nLIMIT 100",
    },
    "most-connected": {
        "label": "Find the most connected entities",
        "description": "Ranks entities by degree, the classic way to find hubs in a graph.",
        "cypher": "MATCH (e:Entity {session_id: $session_id})\nOPTIONAL MATCH (e)-[r:RELATES]-()\nRETURN e.name AS name, e.type AS type, count(r) AS degree\nORDER BY degree DESC\nLIMIT 20",
    },
    "entity-types": {
        "label": "Count entities by type",
        "description": "Aggregation showing what kinds of things the extractor found.",
        "cypher": "MATCH (e:Entity {session_id: $session_id})\nRETURN e.type AS type, count(*) AS total\nORDER BY total DESC",
    },
    "two-hop-paths": {
        "label": "Show two-hop paths",
        "description": "Multi-hop traversal, the capability that makes graph RAG different from vector RAG.",
        "cypher": "MATCH path = (a:Entity {session_id: $session_id})-[:RELATES*2]-(b:Entity {session_id: $session_id})\nWHERE a.name < b.name\nRETURN a.name AS start, [n IN nodes(path) | n.name] AS hops, b.name AS end\nLIMIT 25",
    },
    "orphan-entities": {
        "label": "Find isolated entities",
        "description": "Entities with no relationships, useful for spotting weak extraction.",
        "cypher": "MATCH (e:Entity {session_id: $session_id})\nWHERE NOT (e)-[:RELATES]-()\nRETURN e.name AS name, e.type AS type\nLIMIT 50",
    },
    "chunk-mentions": {
        "label": "Show which chunk mentions which entity",
        "description": "Traverses the MENTIONS edge that links graph nodes back to source text.",
        "cypher": "MATCH (c:Chunk {session_id: $session_id})-[:MENTIONS]->(e:Entity)\nRETURN c.filename AS file, c.position AS chunk, collect(e.name)[0..8] AS entities\nORDER BY chunk\nLIMIT 40",
    },
}


async def graph_rag_user_id(user_id: str = Depends(current_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    if not has_project_access(user, PROJECT_ID):
        raise HTTPException(status_code=403, detail="Graph RAG access has been removed")
    return user_id


def _http_error(error):
    if isinstance(error, (DocumentError, ValueError)):
        return HTTPException(status_code=400, detail=str(error))
    if isinstance(error, graph_store.GraphStoreError):
        return HTTPException(status_code=503, detail=str(error))
    logger.exception("Graph RAG operation failed")
    return HTTPException(status_code=502, detail=str(error))


def _session_payload(session, user_id):
    return {
        "session": session,
        "documents": database.list_documents(session["id"], user_id, include_chunks=True),
        "messages": database.get_messages(session["id"], user_id),
    }


def _stream(events):
    """Serialize a generator of dict events as newline-delimited JSON."""
    def iterator():
        try:
            for event in events:
                yield json.dumps(event) + "\n"
        except (DocumentError, EmbeddingError, ProviderError, graph_store.GraphStoreError, ValueError) as error:
            yield json.dumps({"step": "error", "detail": str(error)}) + "\n"
        except Exception as error:
            logger.exception("Graph RAG stream failed")
            yield json.dumps({"step": "error", "detail": f"Unexpected error: {error}"}) + "\n"

    return StreamingResponse(
        iterator(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sessions")
async def sessions(user_id: str = Depends(graph_rag_user_id)):
    return await asyncio.to_thread(database.list_sessions, user_id)


@router.get("/storage")
async def storage(user_id: str = Depends(graph_rag_user_id)):
    return await asyncio.to_thread(_storage_payload, database, user_id)


@router.get("/queries")
async def query_templates(_: str = Depends(graph_rag_user_id)):
    return [{"id": key, **value} for key, value in QUERY_TEMPLATES.items()]


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(data: SessionCreateRequest, user_id: str = Depends(graph_rag_user_id)):
    return await asyncio.to_thread(
        database.create_session, user_id, data.provider, data.model.strip(), data.embedding_model.strip()
    )


@router.get("/sessions/{session_id}")
async def session(session_id: str, user_id: str = Depends(graph_rag_user_id)):
    item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not item:
        raise HTTPException(status_code=404, detail="Graph RAG session not found")
    return await asyncio.to_thread(_session_payload, item, user_id)


@router.get("/sessions/{session_id}/graph")
async def session_graph(session_id: str, user_id: str = Depends(graph_rag_user_id)):
    if not await asyncio.to_thread(database.get_session, session_id, user_id):
        raise HTTPException(status_code=404, detail="Graph RAG session not found")
    try:
        graph, graph_cypher = await asyncio.to_thread(graph_store.session_graph, session_id)
        stats, stats_cypher = await asyncio.to_thread(graph_store.graph_stats, session_id)
    except graph_store.GraphStoreError as error:
        raise _http_error(error) from error
    return {**graph, "stats": stats, "cypher": [graph_cypher.strip(), stats_cypher.strip()]}


@router.post("/sessions/{session_id}/queries/{template_id}")
async def run_query_template(session_id: str, template_id: str, user_id: str = Depends(graph_rag_user_id)):
    template = QUERY_TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Unknown query template")
    if not await asyncio.to_thread(database.get_session, session_id, user_id):
        raise HTTPException(status_code=404, detail="Graph RAG session not found")
    try:
        rows = await asyncio.to_thread(graph_store._run, template["cypher"], {"session_id": session_id})
    except graph_store.GraphStoreError as error:
        raise _http_error(error) from error
    return {"id": template_id, "cypher": template["cypher"], "rows": rows}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user_id: str = Depends(graph_rag_user_id)):
    item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not item:
        raise HTTPException(status_code=404, detail="Graph RAG session not found")
    documents = await asyncio.to_thread(database.list_documents, session_id, user_id)
    try:
        await asyncio.to_thread(graph_store.delete_session_graph, session_id)
        for document in documents:
            await asyncio.to_thread(bucket_storage.delete, document["remote_path"])
    except (graph_store.GraphStoreError, bucket_storage.BucketError) as error:
        raise _http_error(error) from error
    await asyncio.to_thread(database.delete_session, session_id, user_id)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, user_id: str = Depends(graph_rag_user_id)):
    document = await asyncio.to_thread(database.get_document, document_id, user_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        await asyncio.to_thread(graph_store.delete_document_graph, document["session_id"], document_id)
        await asyncio.to_thread(bucket_storage.delete, document["remote_path"])
    except (graph_store.GraphStoreError, bucket_storage.BucketError) as error:
        raise _http_error(error) from error
    await asyncio.to_thread(database.delete_document, document_id, user_id)


@router.post("/sessions/{session_id}/documents")
async def upload_document(
    session_id: str,
    file: UploadFile = File(...),
    provider: str = Form(...),
    api_key: str = Form(...),
    model: str = Form(...),
    embedding_api_key: str = Form(...),
    embedding_model: str = Form("gemini-embedding-001"),
    chunk_size: int = Form(900),
    overlap: int = Form(120),
    user_id: str = Depends(graph_rag_user_id),
):
    """Build the knowledge graph, streaming every step as newline-delimited JSON."""
    session_item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not session_item:
        raise HTTPException(status_code=404, detail="Graph RAG session not found")

    content = await file.read(MAX_FILE_SIZE + 1)
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="The document exceeds the 3 MB limit")
    filename = Path(file.filename or "document").name
    content_hash = hashlib.sha256(content).hexdigest()
    if await asyncio.to_thread(database.find_document_by_hash, user_id, content_hash):
        raise HTTPException(status_code=409, detail="This document has already been added")
    try:
        await asyncio.to_thread(_check_storage_quota, database, user_id, len(content))
        text = await asyncio.to_thread(extract_text, filename, content)
    except (DocumentError, ValueError) as error:
        raise _http_error(error) from error

    document_id = uuid4().hex
    remote_path = f"users/{user_id}/graph-rag/{session_id}/documents/{document_id}{Path(filename).suffix.lower()}"
    content_type = file.content_type or "application/octet-stream"

    def events():
        yield {"step": "start", "message": f"Reading {filename}", "filename": filename, "size": len(content)}
        stored = False
        try:
            for event in pipeline.ingest_document(
                session_id, user_id, document_id, filename, text, provider, api_key,
                model, embedding_api_key, embedding_model, chunk_size, overlap,
            ):
                if event["step"] == "graph-complete":
                    bucket_storage.upload(content, remote_path)
                    stored = True
                    document = database.save_document(
                        document_id, session_id, filename, content_type, len(content),
                        "recursive", chunk_size, overlap, remote_path, event.pop("chunks"), content_hash,
                    )
                    if not document:
                        raise ValueError("This session was deleted while the graph was being built")
                    event["document"] = document
                yield event
        except Exception:
            graph_store.delete_document_graph(session_id, document_id)
            if stored:
                try:
                    bucket_storage.delete(remote_path)
                except bucket_storage.BucketError:
                    logger.warning("Could not roll back stored document %s", remote_path)
            raise

    return _stream(events())


@router.post("/messages")
async def send_message(data: GraphChatRequest, user_id: str = Depends(graph_rag_user_id)):
    """Answer from the knowledge graph, streaming each retrieval step."""
    session_item = await asyncio.to_thread(database.get_session, data.session_id, user_id)
    if not session_item:
        raise HTTPException(status_code=404, detail="Graph RAG session not found")
    if not await asyncio.to_thread(database.list_documents, data.session_id, user_id):
        raise HTTPException(status_code=400, detail="Add at least one document before asking questions")
    history = await asyncio.to_thread(database.get_messages, data.session_id, user_id)
    question = data.message.strip()

    def events():
        for event in pipeline.answer_question(
            data.session_id, question, data.provider, data.api_key, data.model.strip(),
            data.embedding_api_key, data.embedding_model.strip(), data.top_k, data.hops, history,
        ):
            if event["step"] == "answer":
                database.add_exchange(
                    data.session_id, question, event["answer"], event["citations"], event["trace"]
                )
            yield event

    return _stream(events())
