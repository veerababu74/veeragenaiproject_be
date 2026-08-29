from typing import Literal

from pydantic import BaseModel, Field


Provider = Literal["openai", "gemini", "mistral", "groq", "openrouter"]


class ChatRequest(BaseModel):
    session_id: str | None = None
    provider: Provider
    api_key: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=20_000)


class SessionCreateRequest(BaseModel):
    provider: Provider
    model: str = Field(min_length=1, max_length=120)


class MessageResponse(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: int


class SessionResponse(BaseModel):
    id: str
    title: str
    provider: Provider
    model: str
    created_at: int
    expires_at: int


class ChatResponse(BaseModel):
    session: SessionResponse
    messages: list[MessageResponse]