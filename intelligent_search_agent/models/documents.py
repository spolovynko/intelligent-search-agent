from typing import Any

from pydantic import BaseModel


class DocumentChunkResult(BaseModel):
    id: int
    document_id: int
    chunk_index: int
    heading: str | None = None
    content: str
    page_number: int | None = None
    metadata: dict[str, Any] | None = None
    document_title: str | None = None
    source_uri: str | None = None
    doc_type: str | None = None
    language: str | None = None
    similarity: float | None = None
    vec_score: float | None = None
    kw_score: float | None = None


class DocumentSearchResponse(BaseModel):
    query: str
    results: list[DocumentChunkResult]
    count: int
