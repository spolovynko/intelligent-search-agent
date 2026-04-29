from typing import Any, Literal

from pydantic import BaseModel


class UnifiedSearchResult(BaseModel):
    source: Literal["asset", "document", "meeting"]
    title: str | None = None
    summary: str | None = None
    url: str | None = None
    score: float | None = None
    payload: dict[str, Any]


class UnifiedSearchResponse(BaseModel):
    query: str
    results: list[UnifiedSearchResult]
    count: int
