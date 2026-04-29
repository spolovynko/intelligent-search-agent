from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatFilters(BaseModel):
    source_types: list[Literal["assets", "documents", "meetings"]] = Field(default_factory=list)
    year: int | None = None
    language: str | None = None
    asset_kind: str | None = None
    file_type: str | None = None
    period: str | None = None
    campaign_context: str | None = None
    doc_type: str | None = None


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None
    messages: list[ChatMessage] = Field(default_factory=list)
    filters: ChatFilters | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
