from fastapi import APIRouter, Query

from intelligent_search_agent.db import Database
from intelligent_search_agent.models.search import UnifiedSearchResponse

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.get("", response_model=UnifiedSearchResponse)
async def unified_search(
    q: str = Query(description="Search query"),
    sources: list[str] = Query(default=["assets", "documents", "meetings"]),
    limit: int = Query(default=5, ge=1, le=25),
) -> UnifiedSearchResponse:
    db = Database()
    results = []

    if "assets" in sources:
        for row in await db.assets.search(q, limit=limit):
            results.append(
                {
                    "source": "asset",
                    "title": row.get("file_name") or row.get("description"),
                    "summary": row.get("description") or row.get("asset_content"),
                    "url": f"/v1/assets/{row['id']}",
                    "score": row.get("similarity"),
                    "payload": row,
                }
            )

    if "documents" in sources:
        for row in await db.documents.search(q, limit=limit):
            results.append(
                {
                    "source": "document",
                    "title": row.get("document_title"),
                    "summary": row.get("content"),
                    "url": row.get("source_uri"),
                    "score": row.get("similarity"),
                    "payload": row,
                }
            )

    if "meetings" in sources:
        for row in await db.meetings.search_topics(q, limit=limit):
            results.append(
                {
                    "source": "meeting",
                    "title": row.get("topic") or row.get("meeting_title"),
                    "summary": row.get("content"),
                    "url": f"/v1/meetings/{row['meeting_id']}" if row.get("meeting_id") else None,
                    "score": row.get("similarity"),
                    "payload": row,
                }
            )

    results.sort(key=lambda item: item.get("score") or 0, reverse=True)
    return {"query": q, "results": results, "count": len(results)}
