from pydantic import BaseModel, Field

from basichatapp.models import Provider


class SessionCreateRequest(BaseModel):
    provider: Provider
    model: str = Field(min_length=1, max_length=120)
    embedding_model: str = Field(default="gemini-embedding-001", min_length=1, max_length=120)


class GraphChatRequest(BaseModel):
    session_id: str
    provider: Provider
    api_key: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    embedding_api_key: str = Field(min_length=8, max_length=500)
    embedding_model: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=20_000)
    top_k: int = Field(default=5, ge=1, le=10)
    hops: int = Field(default=2, ge=1, le=3)
