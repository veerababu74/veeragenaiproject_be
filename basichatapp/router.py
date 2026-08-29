import asyncio

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status

from Authentication.database import users
from Authentication.security import current_user_id, has_project_access

from . import database
from .models import ChatRequest, ChatResponse, MessageResponse, SessionCreateRequest, SessionResponse
from .providers import ProviderError, chat


PROJECT_ID = "basic-chat"
router = APIRouter(prefix="/basic-chat", tags=["Basic Chat"])


async def chat_user_id(user_id: str = Depends(current_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    if not has_project_access(user, PROJECT_ID):
        raise HTTPException(status_code=403, detail="Basic Chat access has been removed")
    return user_id


@router.get("/sessions", response_model=list[SessionResponse])
async def sessions(user_id: str = Depends(chat_user_id)):
    return await asyncio.to_thread(database.list_sessions, user_id)


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(data: SessionCreateRequest, user_id: str = Depends(chat_user_id)):
    return await asyncio.to_thread(
        database.create_session, user_id, data.provider, data.model.strip(), "New chat"
    )


@router.get("/sessions/{session_id}", response_model=ChatResponse)
async def session(session_id: str, user_id: str = Depends(chat_user_id)):
    document = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not document:
        raise HTTPException(status_code=404, detail="Chat session not found")
    messages = await asyncio.to_thread(database.get_messages, session_id)
    return ChatResponse(session=SessionResponse(**document), messages=messages)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user_id: str = Depends(chat_user_id)):
    deleted = await asyncio.to_thread(database.delete_session, session_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat session not found")


@router.post("/messages", response_model=ChatResponse)
async def send_message(data: ChatRequest, user_id: str = Depends(chat_user_id)):
    await asyncio.to_thread(database.cleanup_expired)
    document = None
    if data.session_id:
        document = await asyncio.to_thread(database.get_session, data.session_id, user_id)
        if not document:
            raise HTTPException(status_code=404, detail="Chat session not found")
        if document["provider"] != data.provider or document["model"] != data.model:
            raise HTTPException(status_code=400, detail="Start a new chat to change provider or model")

    history = await asyncio.to_thread(database.get_messages, data.session_id) if document else []
    provider_messages = [
        {"role": message["role"], "content": message["content"]} for message in history
    ]
    provider_messages.append({"role": "user", "content": data.message.strip()})
    try:
        answer = await asyncio.to_thread(
            chat, data.provider, data.api_key, data.model.strip(), provider_messages
        )
    except ProviderError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error

    if not document:
        document = await asyncio.to_thread(
            database.create_session,
            user_id,
            data.provider,
            data.model.strip(),
            data.message,
        )
    elif not history:
        document["title"] = await asyncio.to_thread(
            database.update_session_title, document["id"], data.message
        )
    document["expires_at"] = await asyncio.to_thread(
        database.add_exchange, document["id"], data.message.strip(), answer
    )
    messages = await asyncio.to_thread(database.get_messages, document["id"])
    return ChatResponse(
        session=SessionResponse(**document),
        messages=[MessageResponse(**message) for message in messages],
    )