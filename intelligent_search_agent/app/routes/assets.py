import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse

from intelligent_search_agent.db import Database
from intelligent_search_agent.models import AssetInfo, AssetSearchResponse
from intelligent_search_agent.core.security import source_url_allowed
from intelligent_search_agent.retrieval.storage import file_url_from_path, resolve_asset_path

router = APIRouter(prefix="/v1/assets", tags=["assets"])

INLINE_TYPES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".pdf", ".mp4", ".webm"}


def _with_urls(row: dict) -> dict:
    row = dict(row)
    row["preview_url"] = f"/v1/assets/{row['id']}/file"
    row["download_url"] = f"/v1/assets/{row['id']}/file?download=true"
    return row


@router.get("/search", response_model=AssetSearchResponse)
async def search_assets(
    q: str = Query(description="Semantic search query"),
    limit: int = Query(default=10, ge=1, le=100),
    asset_kind: str | None = None,
    language: str | None = None,
    file_type: str | None = None,
    year: int | None = None,
    campaign_context: str | None = None,
    period: str | None = None,
) -> AssetSearchResponse:
    db = Database()
    results = await db.assets.search(
        q,
        limit=limit,
        asset_kind=asset_kind,
        language=language,
        file_type=file_type,
        year=year,
        campaign_context=campaign_context,
        period=period,
    )
    return {"query": q, "results": [_with_urls(row) for row in results], "count": len(results)}


@router.get("/{asset_id}", response_model=AssetInfo)
async def get_asset(asset_id: int) -> AssetInfo:
    db = Database()
    rows = await db.execute(
        """
        SELECT
            a.id,
            a.external_id,
            a.file_name,
            a.file_path,
            a.file_type,
            a.file_size,
            a.storage_backend,
            a.storage_uri,
            a.source_url,
            a.thumbnail_uri,
            a.asset_kind,
            a.language,
            a.period,
            a.campaign_context,
            a.description,
            a.asset_content,
            a.document_content,
            a.image_width,
            a.image_height,
            a.metadata,
            p.external_id AS project_external_id,
            p.name AS project_name,
            p.year AS project_year
        FROM assets a
        LEFT JOIN projects p ON a.project_id = p.id
        WHERE a.id = %s
        """,
        (asset_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    return _with_urls(rows[0])


@router.get("/{asset_id}/link")
async def get_asset_link(asset_id: int):
    db = Database()
    rows = await db.execute(
        "SELECT file_path, storage_uri, source_url, storage_backend FROM assets WHERE id = %s",
        (asset_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")
    row = rows[0]
    raw_path = row.get("storage_uri") or row.get("file_path")
    return {
        "storage_backend": row.get("storage_backend"),
        "storage_uri": row.get("storage_uri"),
        "source_url": row.get("source_url"),
        "file_url": file_url_from_path(raw_path),
        "raw_path": raw_path,
    }


@router.get("/{asset_id}/file")
async def serve_asset_file(asset_id: int, request: Request, download: bool = False):
    db = Database()
    rows = await db.execute(
        """
        SELECT file_path, file_name, file_type, storage_backend, storage_uri, source_url
        FROM assets
        WHERE id = %s
        """,
        (asset_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Asset {asset_id} not found")

    asset = rows[0]
    file_path = resolve_asset_path(asset.get("file_path"), asset.get("storage_uri"))
    if file_path and file_path.exists():
        content_type, _ = mimetypes.guess_type(str(file_path))
        if not content_type:
            content_type = "application/octet-stream"

        file_name = asset.get("file_name") or Path(file_path).name
        file_type = (asset.get("file_type") or Path(file_path).suffix).lower()
        disposition = "inline" if not download and file_type in INLINE_TYPES else "attachment"

        return FileResponse(
            path=file_path,
            media_type=content_type,
            headers={"Content-Disposition": f'{disposition}; filename="{file_name}"'},
        )

    remote_url = asset.get("storage_uri")
    if not (isinstance(remote_url, str) and remote_url.startswith(("http://", "https://"))):
        remote_url = asset.get("source_url")
    if source_url_allowed(remote_url):
        return RedirectResponse(url=remote_url)

    if not file_path or not file_path.exists():
        link_url = f"/v1/assets/{asset_id}/link"
        raise HTTPException(
            status_code=404,
            detail=f"Asset file is not reachable by the API. Check {link_url} for stored pointers.",
        )
