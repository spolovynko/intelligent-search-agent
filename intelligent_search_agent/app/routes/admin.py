from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query

from intelligent_search_agent.core.config import PROJECT_ROOT, get_settings
from intelligent_search_agent.core.security import require_admin_api_key
from intelligent_search_agent.db import Database

router = APIRouter(
    prefix="/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin_api_key)],
)


def _resolve_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    normalized = str(path).replace("\\", "/")
    if normalized.startswith("/app/storage/") and not path.exists():
        return PROJECT_ROOT / "storage" / normalized.removeprefix("/app/storage/")
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def _path_exists(raw_path: str | None) -> bool:
    path = _resolve_path(raw_path)
    return bool(path and path.exists())


async def _counts(db: Database) -> dict[str, Any]:
    rows = await db.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM assets) AS assets,
            (SELECT COUNT(*) FROM assets WHERE embedding IS NULL) AS assets_missing_embeddings,
            (SELECT COUNT(*) FROM documents) AS documents,
            (SELECT COUNT(*) FROM document_chunks) AS document_chunks,
            (SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL) AS chunks_missing_embeddings,
            (SELECT COUNT(*) FROM chat_sessions) AS chat_sessions,
            (SELECT COUNT(*) FROM chat_messages) AS chat_messages
        """
    )
    return dict(rows[0]) if rows else {}


async def _asset_missing_files(db: Database, limit: int = 500) -> list[dict[str, Any]]:
    rows = await db.execute(
        """
        SELECT id, file_name, file_path, storage_uri, storage_backend, source_url
        FROM assets
        WHERE COALESCE(storage_backend, 'local') = 'local'
        ORDER BY id
        LIMIT %s
        """,
        (limit,),
    )

    missing: list[dict[str, Any]] = []
    settings = get_settings()
    for row in rows:
        raw_path = row.get("file_path")
        if not raw_path and row.get("storage_uri"):
            raw_path = str(settings.asset_root / row["storage_uri"])
        if not _path_exists(raw_path):
            missing.append({**row, "resolved_path": str(_resolve_path(raw_path) or "")})
    return missing


async def _document_missing_files(db: Database, limit: int = 500) -> list[dict[str, Any]]:
    rows = await db.execute(
        """
        SELECT
            id,
            title,
            source_uri,
            metadata #>> '{source_manifest,local_path}' AS local_path
        FROM documents
        ORDER BY id
        LIMIT %s
        """,
        (limit,),
    )

    missing: list[dict[str, Any]] = []
    for row in rows:
        raw_path = row.get("local_path")
        if raw_path and not _path_exists(raw_path):
            missing.append({**row, "resolved_path": str(_resolve_path(raw_path) or "")})
    return missing


@router.get("/corpus/status")
async def corpus_status():
    db = Database()
    counts = await _counts(db)
    missing_assets = await _asset_missing_files(db, limit=1000)
    missing_documents = await _document_missing_files(db, limit=1000)
    duplicate_rows = await db.execute(
        """
        SELECT content_hash, COUNT(*) AS count
        FROM assets
        WHERE content_hash IS NOT NULL
        GROUP BY content_hash
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
        LIMIT 25
        """
    )

    vlm_cache = PROJECT_ROOT / "storage" / "manifests" / "image_vlm_entries.jsonl"
    vlm_cache_lines = 0
    if vlm_cache.exists():
        vlm_cache_lines = sum(
            1 for line in vlm_cache.read_text(encoding="utf-8").splitlines() if line.strip()
        )

    return {
        "counts": counts,
        "missing_files": {
            "assets": len(missing_assets),
            "documents": len(missing_documents),
        },
        "duplicate_asset_hash_groups": len(duplicate_rows),
        "vlm_cache": {
            "path": str(vlm_cache),
            "exists": vlm_cache.exists(),
            "entries": vlm_cache_lines,
        },
    }


@router.get("/corpus/missing-files")
async def corpus_missing_files(limit: int = Query(default=500, ge=1, le=2000)):
    db = Database()
    return {
        "assets": await _asset_missing_files(db, limit=limit),
        "documents": await _document_missing_files(db, limit=limit),
    }


@router.get("/corpus/duplicates")
async def corpus_duplicates():
    db = Database()
    rows = await db.execute(
        """
        SELECT id, content_hash, file_name, file_path, source_url
        FROM assets
        WHERE content_hash IN (
            SELECT content_hash
            FROM assets
            WHERE content_hash IS NOT NULL
            GROUP BY content_hash
            HAVING COUNT(*) > 1
        )
        ORDER BY content_hash, id
        """
    )
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["content_hash"])].append(row)
    return {"groups": dict(groups), "count": len(groups)}


@router.get("/chat/sessions")
async def chat_sessions(limit: int = Query(default=25, ge=1, le=100)):
    db = Database()
    return {"sessions": await db.chat.list_sessions(limit=limit)}


@router.get("/chat/sessions/{session_id}/messages")
async def chat_session_messages(session_id: str, limit: int = Query(default=50, ge=1, le=200)):
    db = Database()
    return {
        "session_id": session_id,
        "messages": await db.chat.recent_messages(session_id, limit=limit),
    }
