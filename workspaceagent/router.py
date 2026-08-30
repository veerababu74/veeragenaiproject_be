import asyncio
import logging
from urllib.parse import quote

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from Authentication.config import settings
from Authentication.database import users
from Authentication.security import current_user_id, has_project_access
from basichatapp.providers import ProviderError

from . import database
from .agent import execute_confirmed, run_agent
from .google_tools import GoogleToolError, GoogleWorkspace
from .models import AgentRequest, ConfirmRequest
from .oauth import (
    GoogleConnectionError, authorization_url, create_state, decrypt_token, encrypt_token,
    exchange_code, google_email, read_state_payload, refresh_access_token, revoke,
)


PROJECT_ID = "google-workspace-agent"
router = APIRouter(prefix="/workspace-agent", tags=["Google Workspace Agent"])
logger = logging.getLogger("veera.workspace_agent")


async def agent_user_id(user_id: str = Depends(current_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    if not has_project_access(user, PROJECT_ID):
        raise HTTPException(status_code=403, detail="Google Workspace Agent access has been removed")
    return user_id


def _require_oauth_config():
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(status_code=503, detail="Google Workspace OAuth is not configured")


async def _workspace(user_id):
    user = await users.find_one({"_id": ObjectId(user_id)})
    connection = user.get("google_workspace") if user else None
    if not connection or not connection.get("refresh_token"):
        raise HTTPException(status_code=409, detail="Connect Gmail and Google Calendar first")
    _require_oauth_config()
    try:
        refresh_token = decrypt_token(connection["refresh_token"], settings.jwt_secret)
        access_token = await asyncio.to_thread(refresh_access_token, refresh_token, settings.google_client_id, settings.google_client_secret)
    except GoogleConnectionError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error
    return GoogleWorkspace(access_token)


def _payload(session, user_id):
    return {"session": session, "messages": database.get_messages(session["id"], user_id)}


@router.get("/connection")
async def connection(user_id: str = Depends(agent_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    linked = user.get("google_workspace") if user else None
    return {
        "connected": bool(linked),
        "configured": bool(settings.google_client_id and settings.google_client_secret),
        "email": linked.get("email") if linked else None,
    }


@router.get("/google/authorize")
async def google_authorize(
    return_url: str | None = Query(default=None),
    user_id: str = Depends(agent_user_id),
):
    _require_oauth_config()
    return_url = (return_url or settings.frontend_url).rstrip("/")
    if return_url not in settings.frontend_url_set:
        raise HTTPException(status_code=400, detail="Unsupported frontend URL")
    state = create_state(user_id, settings.jwt_secret, return_url)
    return {"authorization_url": authorization_url(
        settings.google_client_id, settings.google_client_secret,
        settings.google_workspace_redirect_uri, state,
    )}


@router.get("/google/callback")
async def google_callback(code: str = "", state: str = "", error: str = ""):
    destination = f"{settings.frontend_url.rstrip('/')}/projects/{PROJECT_ID}"
    try:
        state_payload = read_state_payload(state, settings.jwt_secret)
        return_url = state_payload.get("return_url", settings.frontend_url).rstrip("/")
        if return_url in settings.frontend_url_set:
            destination = f"{return_url}/projects/{PROJECT_ID}"
        if error:
            return RedirectResponse(f"{destination}?google_error={quote(error)}")
        _require_oauth_config()
        user_id = state_payload["sub"]
        data = await asyncio.to_thread(exchange_code, code, settings.google_client_id, settings.google_client_secret, settings.google_workspace_redirect_uri)
        email = await asyncio.to_thread(google_email, data["access_token"])
        await users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"google_workspace": {"email": email, "refresh_token": encrypt_token(data["refresh_token"], settings.jwt_secret), "scope": data.get("scope", "")}}},
        )
    except (GoogleConnectionError, HTTPException, ValueError) as callback_error:
        detail = callback_error.detail if isinstance(callback_error, HTTPException) else str(callback_error)
        cause = callback_error.__cause__
        logger.warning(
            "Google OAuth callback failed | error=%s | cause=%s | oauth_error=%s",
            type(callback_error).__name__,
            type(cause).__name__ if cause else "none",
            getattr(cause, "error", "unknown"),
        )
        return RedirectResponse(f"{destination}?google_error={quote(detail)}")
    return RedirectResponse(f"{destination}?google=linked")


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_google(user_id: str = Depends(agent_user_id)):
    user = await users.find_one({"_id": ObjectId(user_id)})
    connection_data = user.get("google_workspace") if user else None
    if connection_data and connection_data.get("refresh_token"):
        try:
            token = decrypt_token(connection_data["refresh_token"], settings.jwt_secret)
            await asyncio.to_thread(revoke, token)
        except GoogleConnectionError:
            pass
    await users.update_one({"_id": ObjectId(user_id)}, {"$unset": {"google_workspace": ""}})


@router.get("/sessions")
async def sessions(user_id: str = Depends(agent_user_id)):
    return await asyncio.to_thread(database.list_sessions, user_id)


@router.get("/sessions/{session_id}")
async def session(session_id: str, user_id: str = Depends(agent_user_id)):
    item = await asyncio.to_thread(database.get_session, session_id, user_id)
    if not item:
        raise HTTPException(status_code=404, detail="Workspace agent session not found")
    return await asyncio.to_thread(_payload, item, user_id)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(session_id: str, user_id: str = Depends(agent_user_id)):
    if not await asyncio.to_thread(database.delete_session, session_id, user_id):
        raise HTTPException(status_code=404, detail="Workspace agent session not found")


@router.post("/messages")
async def send_message(data: AgentRequest, user_id: str = Depends(agent_user_id)):
    workspace = await _workspace(user_id)
    item = await asyncio.to_thread(database.get_session, data.session_id, user_id) if data.session_id else None
    if data.session_id and not item:
        raise HTTPException(status_code=404, detail="Workspace agent session not found")
    if item and (item["provider"], item["model"]) != (data.provider, data.model.strip()):
        raise HTTPException(status_code=400, detail="Start a new session to change provider or model")
    if not item:
        item = await asyncio.to_thread(database.create_session, user_id, data.provider, data.model.strip())
    history = await asyncio.to_thread(database.get_messages, item["id"], user_id)
    logger.info("Workspace agent request | user=%s | session=%s", user_id, item["id"])
    try:
        result = await asyncio.to_thread(run_agent, data.message.strip(), history, data.provider, data.api_key, data.model.strip(), workspace)
    except (ProviderError, GoogleToolError, ValueError) as error:
        logger.warning("Workspace agent request failed | %s", error)
        raise HTTPException(status_code=502, detail=str(error)) from error
    message_id = await asyncio.to_thread(database.add_exchange, item["id"], data.message.strip(), result)
    if not message_id:
        raise HTTPException(status_code=409, detail="This agent session was deleted while the request was running")
    return await asyncio.to_thread(_payload, item, user_id)


@router.post("/actions/confirm")
async def confirm_action(data: ConfirmRequest, user_id: str = Depends(agent_user_id)):
    claim = await asyncio.to_thread(database.claim_action, data.message_id, user_id)
    if not claim:
        raise HTTPException(status_code=409, detail="This action is no longer waiting for confirmation")
    try:
        workspace = await _workspace(user_id)
        content, result = await asyncio.to_thread(execute_confirmed, claim["action"], workspace)
        await asyncio.to_thread(database.finish_action, data.message_id, content, result)
    except HTTPException:
        await asyncio.to_thread(database.release_action, data.message_id)
        raise
    except (GoogleToolError, GoogleConnectionError, ValueError) as error:
        await asyncio.to_thread(database.release_action, data.message_id)
        raise HTTPException(status_code=502, detail=str(error)) from error
    session_item = await asyncio.to_thread(database.get_session, claim["session_id"], user_id)
    return await asyncio.to_thread(_payload, session_item, user_id)
