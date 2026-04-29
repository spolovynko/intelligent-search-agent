from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AssetInfo(BaseModel):
    id: int
    external_id: str | None = None
    file_name: str | None = None
    file_path: str | None = None
    file_type: str | None = None
    file_size: int | None = None
    storage_backend: str | None = None
    storage_uri: str | None = None
    source_url: str | None = None
    thumbnail_uri: str | None = None
    asset_kind: str | None = None
    language: str | None = None
    period: str | None = None
    campaign_context: str | None = None
    description: str | None = None
    asset_content: str | None = None
    document_content: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    metadata: dict[str, Any] | None = None
    project_external_id: str | None = None
    project_name: str | None = None
    project_year: int | None = None
    similarity: float | None = None
    vec_score: float | None = None
    kw_score: float | None = None
    preview_url: str | None = None
    download_url: str | None = None
    created_at: datetime | None = None


class AssetSearchResponse(BaseModel):
    query: str
    results: list[AssetInfo]
    count: int


class AssetSearchFilters(BaseModel):
    q: str = Field(description="Semantic search query")
    limit: int = Field(default=10, ge=1, le=100)
    asset_kind: str | None = None
    language: str | None = None
    file_type: str | None = None
    year: int | None = None
    campaign_context: str | None = None
    period: str | None = None
