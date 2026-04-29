import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse

from intelligent_search_agent.core.config import PROJECT_ROOT
from intelligent_search_agent.core.security import source_url_allowed
from intelligent_search_agent.db import Database
from intelligent_search_agent.models import DocumentSearchResponse

router = APIRouter(prefix="/v1/documents", tags=["documents"])


def _resolve_document_path(row: dict) -> Path | None:
    metadata = row.get("metadata") or {}
    manifest = metadata.get("source_manifest") or {}
    local_path = manifest.get("local_path")
    if not local_path:
        return None

    path = Path(local_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path if path.exists() else None


def _with_document_urls(row: dict) -> dict:
    row = dict(row)
    row["detail_url"] = f"/v1/documents/{row['id']}"
    row["file_url"] = f"/v1/documents/{row['id']}/file"
    return row


@router.get("/search", response_model=DocumentSearchResponse)
async def search_documents(
    q: str = Query(description="Semantic search query"),
    limit: int = Query(default=10, ge=1, le=100),
    doc_type: str | None = None,
    language: str | None = None,
) -> DocumentSearchResponse:
    db = Database()
    results = await db.documents.search(q, limit=limit, doc_type=doc_type, language=language)
    return {"query": q, "results": results, "count": len(results)}


@router.get("/{document_id}")
async def get_document(document_id: int):
    db = Database()
    rows = await db.execute(
        """
        SELECT id, external_id, title, source_uri, doc_type, language, metadata, created_at, updated_at
        FROM documents
        WHERE id = %s
        """,
        (document_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
    return _with_document_urls(rows[0])


@router.get("/{document_id}/chunks")
async def get_document_chunks(document_id: int):
    db = Database()
    rows = await db.execute(
        """
        SELECT id, document_id, chunk_index, heading, content, page_number, metadata
        FROM document_chunks
        WHERE document_id = %s
        ORDER BY chunk_index
        """,
        (document_id,),
    )
    return {"document_id": document_id, "chunks": rows, "count": len(rows)}


@router.get("/{document_id}/file")
async def serve_document_file(document_id: int, download: bool = False):
    db = Database()
    rows = await db.execute(
        """
        SELECT id, title, source_uri, metadata
        FROM documents
        WHERE id = %s
        """,
        (document_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    document = rows[0]
    local_path = _resolve_document_path(document)
    if local_path:
        content_type, _ = mimetypes.guess_type(str(local_path))
        file_name = local_path.name
        disposition = "attachment" if download else "inline"
        return FileResponse(
            local_path,
            media_type=content_type or "application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="{file_name}"'},
        )

    source_uri = document.get("source_uri")
    if source_url_allowed(source_uri):
        return RedirectResponse(source_uri)

    raise HTTPException(
        status_code=404,
        detail="Document file is not reachable locally and no HTTP source URI is stored.",
    )
