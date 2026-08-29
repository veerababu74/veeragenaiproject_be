import asyncio
import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from Authentication.database import users
from Authentication.security import current_user_id, has_project_access
from basichatapp.providers import ProviderError, chat

from . import bucket_storage, database, vector_store
from .database import DuplicateDocumentError, StorageQuotaError
from .chunking import chunk_text, recursive_chunks, semantic_chunks, sentences
from .documents import DocumentError, MAX_FILE_SIZE, extract_text
from .embeddings import EmbeddingError, embed_texts
from .models import ChunkStrategy, RagChatRequest, SessionCreateRequest


PROJECT_ID = "basic-rag"
router = APIRouter(prefix="/basic-rag", tags=["Basic RAG"])
logger = logging.getLogger("veera.rag")


async def rag_user_id(user_id: str = Depends(current_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    if not has_project_access(user, PROJECT_ID):
        raise HTTPException(status_code=403, detail="Basic RAG access has been removed")
    return user_id


def _http_error(error):
    if isinstance(error, (DocumentError, ValueError)):
        logger.warning("RAG request rejected | %s", error)
        return HTTPException(status_code=400, detail=str(error))
    logger.exception("RAG operation failed | %s", error)
    return HTTPException(status_code=502, detail=str(error))


def _make_chunks(strategy, text, chunk_size, overlap, embedding_api_key, embedding_model):
    if strategy != "semantic":
        return chunk_text(strategy, text, chunk_size, overlap)
    if not embedding_api_key:
        raise DocumentError("Enter a Google Gemini embedding API key for semantic chunking")
    units = sentences(text)
    vectors = embed_texts(embedding_api_key, embedding_model, units, "SEMANTIC_SIMILARITY")
    return [chunk for block in semantic_chunks(units, vectors) for chunk in recursive_chunks(block, chunk_size, overlap)]


def _check_storage_quota(storage, user_id, size):
    used = storage.document_storage_used(user_id)
    if used + size > storage.MAX_USER_STORAGE:
        remaining_mb = max(0, storage.MAX_USER_STORAGE - used) / (1024 * 1024)
        raise StorageQuotaError(f"Only {remaining_mb:.2f} MB of the 5 MB document allowance remains")


def _storage_payload(storage, user_id):
    used = storage.document_storage_used(user_id)
    return {"used": used, "limit": storage.MAX_USER_STORAGE, "remaining": storage.MAX_USER_STORAGE - used}


def _session_payload(session, user_id):
    return {
        "session": session,
        "documents": database.list_documents(session["id"], user_id, include_chunks=True),
        "messages": database.get_messages(session["id"], user_id),
    }


def _rollback_document(user_id, document_id, chunk_count, remote_path):
    try:
        vector_store.delete_document(user_id, document_id, chunk_count)
    except vector_store.VectorStoreError:
        pass
    try:
        bucket_storage.delete(remote_path)
    except bucket_storage.BucketError:
        pass


@router.get("/sessions")
async def sessions(user_id: str = Depends(rag_user_id)):
    return await asyncio.to_thread(database.list_sessions, user_id)


@router.get("/storage")
async def storage(user_id: str = Depends(rag_user_id)):
    return await asyncio.to_thread(_storage_payload, database, user_id)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(data: SessionCreateRequest, user_id: str = Depends(rag_user_id)):
    return await asyncio.to_thread(database.create_session, user_id, data.provider, data.model.strip(), data.embedding_model.strip())


@router.get("/sessions/{session_id}")
async def session(session_id: str, user_id: str = Depends(rag_user_id)):
    item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not item:
        raise HTTPException(status_code=404, detail="RAG session not found")
    return await asyncio.to_thread(_session_payload, item, user_id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user_id: str = Depends(rag_user_id)):
    item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not item:
        raise HTTPException(status_code=404, detail="RAG session not found")
    documents = await asyncio.to_thread(database.list_documents, session_id, user_id)
    try:
        for document in documents:
            await asyncio.to_thread(vector_store.delete_document, user_id, document["id"], document["chunk_count"])
            await asyncio.to_thread(bucket_storage.delete, document["remote_path"])
    except (vector_store.VectorStoreError, bucket_storage.BucketError) as error:
        raise _http_error(error) from error
    await asyncio.to_thread(database.delete_session, session_id, user_id)


@router.post("/preview")
async def preview_document(
    file: UploadFile = File(...), strategy: ChunkStrategy = Form("recursive"),
    chunk_size: int = Form(800), overlap: int = Form(120),
    embedding_api_key: str = Form(""), embedding_model: str = Form("gemini-embedding-001"),
    _: str = Depends(rag_user_id),
):
    content = await file.read(MAX_FILE_SIZE + 1)
    try:
        text = await asyncio.to_thread(extract_text, file.filename or "document", content)
        chunks = await asyncio.to_thread(_make_chunks, strategy, text, chunk_size, overlap, embedding_api_key, embedding_model)
    except (DocumentError, EmbeddingError, ValueError) as error:
        raise _http_error(error) from error
    return {"filename": Path(file.filename or "document").name, "character_count": len(text), "chunks": chunks, "overlap": overlap}


@router.post("/sessions/{session_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    session_id: str, file: UploadFile = File(...), strategy: ChunkStrategy = Form("recursive"),
    chunk_size: int = Form(800), overlap: int = Form(120),
    embedding_api_key: str = Form(...), embedding_model: str = Form("gemini-embedding-001"),
    user_id: str = Depends(rag_user_id),
):
    session = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="RAG session not found")
    if session["embedding_model"] != embedding_model.strip():
        raise HTTPException(status_code=400, detail="Start a new RAG session to change the embedding model")
    content = await file.read(MAX_FILE_SIZE + 1)
    filename = Path(file.filename or "document").name
    content_hash = hashlib.sha256(content).hexdigest()
    duplicate = await asyncio.to_thread(database.find_document_by_hash, user_id, content_hash)
    if duplicate:
        raise HTTPException(status_code=409, detail=f"Document already exists: {duplicate['filename']}")
    document_id = uuid4().hex
    remote_path = f"users/{user_id}/sessions/{session_id}/documents/{document_id}{Path(filename).suffix.lower()}"
    logger.info("Indexing document | session=%s | document=%s | filename=%s | strategy=%s", session_id, document_id, filename, strategy)
    try:
        await asyncio.to_thread(_check_storage_quota, database, user_id, len(content))
        text = await asyncio.to_thread(extract_text, filename, content)
        chunks = await asyncio.to_thread(_make_chunks, strategy, text, chunk_size, overlap, embedding_api_key, embedding_model)
        vectors = await asyncio.to_thread(embed_texts, embedding_api_key, embedding_model, chunks, "RETRIEVAL_DOCUMENT")
        await asyncio.to_thread(bucket_storage.upload, content, remote_path)
        try:
            await asyncio.to_thread(vector_store.upsert, user_id, session_id, document_id, filename, chunks, vectors)
            document = await asyncio.to_thread(
                database.save_document, document_id, session_id, filename,
                file.content_type or "application/octet-stream", len(content), strategy,
                chunk_size, overlap, remote_path, chunks, database.DATABASE_PATH, content_hash,
            )
            if not document:
                raise HTTPException(status_code=409, detail="This RAG session was deleted while the document was being indexed")
        except Exception:
            await asyncio.to_thread(_rollback_document, user_id, document_id, len(chunks), remote_path)
            raise
    except DuplicateDocumentError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except HTTPException:
        raise
    except (DocumentError, EmbeddingError, bucket_storage.BucketError, vector_store.VectorStoreError, ValueError) as error:
        raise _http_error(error) from error
    logger.info("Document indexed | session=%s | document=%s | chunks=%s", session_id, document_id, len(chunks))
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, user_id: str = Depends(rag_user_id)):
    document = await asyncio.to_thread(database.get_document, document_id, user_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        await asyncio.to_thread(vector_store.delete_document, user_id, document_id, document["chunk_count"])
        await asyncio.to_thread(bucket_storage.delete, document["remote_path"])
    except (vector_store.VectorStoreError, bucket_storage.BucketError) as error:
        raise _http_error(error) from error
    await asyncio.to_thread(database.delete_document, document_id, user_id)


@router.post("/messages")
async def send_message(data: RagChatRequest, user_id: str = Depends(rag_user_id)):
    session = await asyncio.to_thread(database.get_session, data.session_id, user_id)
    if not session:
        raise HTTPException(status_code=404, detail="RAG session not found")
    if (session["provider"], session["model"], session["embedding_model"]) != (data.provider, data.model.strip(), data.embedding_model.strip()):
        raise HTTPException(status_code=400, detail="Start a new RAG session to change models")
    if not await asyncio.to_thread(database.list_documents, data.session_id, user_id):
        raise HTTPException(status_code=400, detail="Upload at least one document before asking questions")
    logger.info("RAG query started | session=%s | provider=%s | top_k=%s", data.session_id, data.provider, data.top_k)
    try:
        query_vector = (await asyncio.to_thread(embed_texts, data.embedding_api_key, data.embedding_model, [data.message], "RETRIEVAL_QUERY"))[0]
        sources = await asyncio.to_thread(vector_store.query, user_id, data.session_id, query_vector, data.top_k)
        context = "\n\n".join(f"[{index}] {source['filename']} (chunk {source['position'] + 1})\n{source['text']}" for index, source in enumerate(sources, 1))
        history = await asyncio.to_thread(database.get_messages, data.session_id, user_id)
        messages = [{"role": item["role"], "content": item["content"]} for item in history[-10:]]
        messages.append({"role": "user", "content": f"Answer only from the supplied sources. If they do not contain the answer, say so. Cite claims with [1], [2], etc.\n\nSOURCES\n{context}\n\nQUESTION\n{data.message.strip()}"})
        answer = await asyncio.to_thread(chat, data.provider, data.api_key, data.model.strip(), messages)
    except (EmbeddingError, vector_store.VectorStoreError, ProviderError) as error:
        raise _http_error(error) from error
    citations = [{"number": index, "filename": source["filename"], "position": source["position"], "score": source["score"], "text": source["text"]} for index, source in enumerate(sources, 1)]
    saved = await asyncio.to_thread(database.add_exchange, data.session_id, data.message.strip(), answer, citations)
    if not saved:
        logger.warning("RAG query discarded because session was deleted | session=%s", data.session_id)
        raise HTTPException(status_code=409, detail="This RAG session was deleted while the answer was being generated")
    logger.info("RAG query complete | session=%s | sources=%s", data.session_id, len(citations))
    session = await asyncio.to_thread(database.get_session, data.session_id, user_id)
    if not session:
        raise HTTPException(status_code=409, detail="This RAG session was deleted while the answer was being generated")
    return await asyncio.to_thread(_session_payload, session, user_id)