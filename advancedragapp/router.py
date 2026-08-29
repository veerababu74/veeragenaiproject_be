import asyncio
import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from Authentication.database import users
from Authentication.security import current_user_id, has_project_access
from basichatapp.providers import ProviderError
from basicragapp import bucket_storage, vector_store
from basicragapp.database import DuplicateDocumentError
from basicragapp.documents import DocumentError, MAX_FILE_SIZE, extract_text
from basicragapp.embeddings import EmbeddingError, embed_texts
from basicragapp.models import ChunkStrategy, RagChatRequest, SessionCreateRequest
from basicragapp.router import _make_chunks, _rollback_document

from . import database
from .pipeline import run_pipeline


PROJECT_ID = "advanced-rag"
router = APIRouter(prefix="/advanced-rag", tags=["Advanced RAG"])
logger = logging.getLogger("veera.advanced_rag")


async def advanced_rag_user_id(user_id: str = Depends(current_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    if not has_project_access(user, PROJECT_ID):
        raise HTTPException(status_code=403, detail="Advanced RAG access has been removed")
    return user_id


def _http_error(error):
    if isinstance(error, (DocumentError, ValueError)):
        logger.warning("Advanced RAG request rejected | %s", error)
        return HTTPException(status_code=400, detail=str(error))
    logger.exception("Advanced RAG operation failed | %s", error)
    return HTTPException(status_code=502, detail=str(error))


def _session_payload(session, user_id):
    return {
        "session": session,
        "documents": database.list_documents(session["id"], user_id, include_chunks=True),
        "messages": database.get_messages(session["id"], user_id),
    }


@router.get("/sessions")
async def sessions(user_id: str = Depends(advanced_rag_user_id)):
    return await asyncio.to_thread(database.list_sessions, user_id)


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(data: SessionCreateRequest, user_id: str = Depends(advanced_rag_user_id)):
    return await asyncio.to_thread(database.create_session, user_id, data.provider, data.model.strip(), data.embedding_model.strip())


@router.get("/sessions/{session_id}")
async def session(session_id: str, user_id: str = Depends(advanced_rag_user_id)):
    item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not item:
        raise HTTPException(status_code=404, detail="Advanced RAG session not found")
    return await asyncio.to_thread(_session_payload, item, user_id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user_id: str = Depends(advanced_rag_user_id)):
    item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not item:
        raise HTTPException(status_code=404, detail="Advanced RAG session not found")
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
    _: str = Depends(advanced_rag_user_id),
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
    user_id: str = Depends(advanced_rag_user_id),
):
    session_item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not session_item:
        raise HTTPException(status_code=404, detail="Advanced RAG session not found")
    if session_item["embedding_model"] != embedding_model.strip():
        raise HTTPException(status_code=400, detail="Start a new Advanced RAG session to change the embedding model")
    content = await file.read(MAX_FILE_SIZE + 1)
    filename = Path(file.filename or "document").name
    content_hash = hashlib.sha256(content).hexdigest()
    duplicate = await asyncio.to_thread(database.find_document_by_hash, user_id, content_hash)
    if duplicate:
        raise HTTPException(status_code=409, detail=f"Document already exists: {duplicate['filename']}")
    document_id = uuid4().hex
    remote_path = f"users/{user_id}/advanced-rag/{session_id}/documents/{document_id}{Path(filename).suffix.lower()}"
    logger.info("Indexing document | session=%s | document=%s | hash=%s", session_id, document_id, content_hash[:12])
    try:
        text = await asyncio.to_thread(extract_text, filename, content)
        chunks = await asyncio.to_thread(_make_chunks, strategy, text, chunk_size, overlap, embedding_api_key, embedding_model)
        vectors = await asyncio.to_thread(embed_texts, embedding_api_key, embedding_model, chunks, "RETRIEVAL_DOCUMENT")
        await asyncio.to_thread(bucket_storage.upload, content, remote_path)
        try:
            await asyncio.to_thread(vector_store.upsert, user_id, session_id, document_id, filename, chunks, vectors)
            document = await asyncio.to_thread(
                database.save_document, document_id, session_id, filename,
                file.content_type or "application/octet-stream", len(content), strategy,
                chunk_size, overlap, remote_path, chunks, content_hash,
            )
            if not document:
                raise HTTPException(status_code=409, detail="This session was deleted while the document was being indexed")
        except Exception:
            await asyncio.to_thread(_rollback_document, user_id, document_id, len(chunks), remote_path)
            raise
    except DuplicateDocumentError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except HTTPException:
        raise
    except (DocumentError, EmbeddingError, bucket_storage.BucketError, vector_store.VectorStoreError, ValueError) as error:
        raise _http_error(error) from error
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, user_id: str = Depends(advanced_rag_user_id)):
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
async def send_message(data: RagChatRequest, user_id: str = Depends(advanced_rag_user_id)):
    session_item = await asyncio.to_thread(database.get_session, data.session_id, user_id)
    if not session_item:
        raise HTTPException(status_code=404, detail="Advanced RAG session not found")
    if (session_item["provider"], session_item["model"], session_item["embedding_model"]) != (data.provider, data.model.strip(), data.embedding_model.strip()):
        raise HTTPException(status_code=400, detail="Start a new Advanced RAG session to change models")
    if not await asyncio.to_thread(database.list_documents, data.session_id, user_id):
        raise HTTPException(status_code=400, detail="Upload at least one document before asking questions")
    history = await asyncio.to_thread(database.get_messages, data.session_id, user_id)
    logger.info("Advanced query started | session=%s | top_k=%s", data.session_id, data.top_k)
    try:
        answer, citations, trace = await asyncio.to_thread(
            run_pipeline, data.message.strip(), user_id, data.session_id, data.provider,
            data.api_key, data.model.strip(), data.embedding_api_key,
            data.embedding_model.strip(), data.top_k, history,
        )
    except (EmbeddingError, vector_store.VectorStoreError, ProviderError) as error:
        raise _http_error(error) from error
    saved = await asyncio.to_thread(database.add_exchange, data.session_id, data.message.strip(), answer, citations, trace)
    if not saved:
        raise HTTPException(status_code=409, detail="This session was deleted while the answer was being generated")
    session_item = await asyncio.to_thread(database.get_session, data.session_id, user_id)
    if not session_item:
        raise HTTPException(status_code=409, detail="This session was deleted while the answer was being generated")
    logger.info("Advanced query complete | session=%s | queries=%s | sources=%s", data.session_id, len(trace["retrievals"]), len(citations))
    return await asyncio.to_thread(_session_payload, session_item, user_id)
