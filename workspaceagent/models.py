from pydantic import BaseModel, Field

from basichatapp.models import Provider


class AgentRequest(BaseModel):
    session_id: str | None = None
    provider: Provider
    api_key: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=10_000)


class ConfirmRequest(BaseModel):
    message_id: int
