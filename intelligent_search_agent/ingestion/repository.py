from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor

from intelligent_search_agent.core.config import PROJECT_ROOT, Settings
from intelligent_search_agent.db.embeddings import vector_to_pg
from intelligent_search_agent.ingestion.common import (
    file_sha256,
    normalize_text,
    resolve_local_path,
    stable_external_id,
    storage_uri_for,
)
from intelligent_search_agent.ingestion.embedding_text import (
    compose_asset_embedding_text,
    compose_document_chunk_embedding_text,
)
from intelligent_search_agent.ingestion.image_analysis import ImageVlmEntry
from intelligent_search_agent.ingestion.pdf_extraction import PdfChunk


def connect_db(settings: Settings):
    kwargs: dict[str, Any] = {
        "host": settings.db_host,
        "port": settings.db_port,
        "dbname": settings.db_name,
        "user": settings.db_user,
        "password": settings.db_password,
        "cursor_factory": RealDictCursor,
    }
    if settings.db_sslmode:
        kwargs["sslmode"] = settings.db_sslmode
    return psycopg2.connect(**kwargs)


def apply_schema(conn) -> None:
    schema_path = PROJECT_ROOT / "sql" / "schema.sql"
    with conn.cursor() as cur:
        cur.execute(schema_path.read_text(encoding="utf-8"))
    conn.commit()


def ensure_project(conn, external_id: str, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO projects (external_id, name, client, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (external_id) DO UPDATE
            SET name = EXCLUDED.name,
                client = EXCLUDED.client,
                metadata = projects.metadata || EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
            """,
            (
                external_id,
                name,
                "Local corpus",
                Json({"domain": "belgian_history", "source": "local downloaded corpus"}),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def asset_has_embedding(conn, external_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM assets WHERE external_id = %s AND embedding IS NOT NULL", (external_id,)
        )
        return cur.fetchone() is not None


def document_has_chunks(conn, external_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.id, COUNT(c.id) AS chunk_count
            FROM documents d
            LEFT JOIN document_chunks c ON c.document_id = d.id
            WHERE d.external_id = %s
            GROUP BY d.id
            """,
            (external_id,),
        )
        row = cur.fetchone()
        return bool(row and int(row["chunk_count"]) > 0)


def build_asset_metadata(
    item: dict[str, Any], entry: ImageVlmEntry, settings: Settings
) -> dict[str, Any]:
    tags = sorted(set(entry.subjects + entry.locations + entry.people + entry.search_keywords))
    return {
        "source_manifest": item,
        "vlm_entry": entry.model_dump(exclude_none=True),
        "tags": tags,
        "image_analysis_model": settings.vision_model,
    }


def build_asset_content(item: dict[str, Any], entry: ImageVlmEntry) -> str:
    return ". ".join(
        part
        for part in [
            f"Subjects: {', '.join(entry.subjects)}" if entry.subjects else "",
            f"Locations: {', '.join(entry.locations)}" if entry.locations else "",
            f"People: {', '.join(entry.people)}" if entry.people else "",
            f"Style: {entry.visual_style}" if entry.visual_style else "",
            f"Keywords: {', '.join(entry.search_keywords)}" if entry.search_keywords else "",
            f"Source search term: {normalize_text(str(item.get('search_term') or ''))}",
        ]
        if part
    )


def upsert_asset(
    conn,
    *,
    project_id: int,
    item: dict[str, Any],
    entry: ImageVlmEntry,
    embedding: list[float],
    settings: Settings,
    project_name: str,
) -> int:
    image_path = resolve_local_path(item["local_path"])
    file_name = image_path.name
    file_type = image_path.suffix.lower()
    file_size = image_path.stat().st_size if image_path.exists() else item.get("bytes")
    storage_uri = storage_uri_for(image_path, settings)
    metadata = build_asset_metadata(item, entry, settings)
    asset_content = build_asset_content(item, entry)
    payload = {
        "description": entry.description,
        "document_content": entry.ocr_text,
        "asset_content": asset_content,
        "asset_kind": entry.asset_kind,
        "campaign_context": entry.campaign_context,
        "language": entry.language or "undetermined",
        "period": entry.period,
        "project_name": project_name,
        "file_name": file_name,
        "metadata": metadata,
    }
    embedding_text = compose_asset_embedding_text(payload)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO assets (
                project_id,
                external_id,
                file_name,
                file_path,
                file_type,
                file_size,
                storage_backend,
                storage_uri,
                source_url,
                thumbnail_uri,
                content_hash,
                asset_kind,
                language,
                period,
                campaign_context,
                description,
                asset_content,
                document_content,
                image_width,
                image_height,
                metadata,
                embedding_text,
                embedding
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s::vector
            )
            ON CONFLICT (external_id) DO UPDATE SET
                project_id = EXCLUDED.project_id,
                file_name = EXCLUDED.file_name,
                file_path = EXCLUDED.file_path,
                file_type = EXCLUDED.file_type,
                file_size = EXCLUDED.file_size,
                storage_backend = EXCLUDED.storage_backend,
                storage_uri = EXCLUDED.storage_uri,
                source_url = EXCLUDED.source_url,
                thumbnail_uri = EXCLUDED.thumbnail_uri,
                content_hash = EXCLUDED.content_hash,
                asset_kind = EXCLUDED.asset_kind,
                language = EXCLUDED.language,
                period = EXCLUDED.period,
                campaign_context = EXCLUDED.campaign_context,
                description = EXCLUDED.description,
                asset_content = EXCLUDED.asset_content,
                document_content = EXCLUDED.document_content,
                image_width = EXCLUDED.image_width,
                image_height = EXCLUDED.image_height,
                metadata = EXCLUDED.metadata,
                embedding_text = EXCLUDED.embedding_text,
                embedding = EXCLUDED.embedding,
                updated_at = NOW()
            RETURNING id
            """,
            (
                project_id,
                stable_external_id("commons", item),
                file_name,
                str(image_path),
                file_type,
                file_size,
                settings.asset_storage_backend,
                storage_uri,
                item.get("source_url"),
                item.get("download_url"),
                file_sha256(image_path) if image_path.exists() else None,
                entry.asset_kind,
                entry.language or "undetermined",
                entry.period,
                entry.campaign_context,
                entry.description,
                asset_content,
                entry.ocr_text,
                item.get("width"),
                item.get("height"),
                Json(metadata),
                embedding_text,
                vector_to_pg(embedding),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def upsert_document(conn, item: dict[str, Any], metadata: dict[str, Any]) -> int:
    external_id = stable_external_id("jbh", item)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO documents (external_id, title, source_uri, doc_type, language, metadata)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (external_id) DO UPDATE SET
                title = EXCLUDED.title,
                source_uri = EXCLUDED.source_uri,
                doc_type = EXCLUDED.doc_type,
                language = EXCLUDED.language,
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            RETURNING id
            """,
            (
                external_id,
                normalize_text(str(item.get("title") or Path(item["local_path"]).name)),
                item.get("source_url"),
                "pdf",
                "undetermined",
                Json({"source_manifest": item, **metadata}),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row["id"])


def delete_document_chunks(conn, document_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM document_chunks WHERE document_id = %s", (document_id,))
    conn.commit()


def upsert_document_chunk(
    conn,
    *,
    document_id: int,
    document_title: str,
    chunk: PdfChunk,
    embedding: list[float],
) -> int:
    embedding_text = compose_document_chunk_embedding_text(
        {
            "document_title": document_title,
            "heading": chunk.heading,
            "content": chunk.content,
            "page_number": chunk.page_number,
        }
    )
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO document_chunks (
                document_id,
                chunk_index,
                heading,
                content,
                page_number,
                metadata,
                embedding_text,
                embedding
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)
            ON CONFLICT (document_id, chunk_index) DO UPDATE SET
                heading = EXCLUDED.heading,
                content = EXCLUDED.content,
                page_number = EXCLUDED.page_number,
                metadata = EXCLUDED.metadata,
                embedding_text = EXCLUDED.embedding_text,
                embedding = EXCLUDED.embedding,
                created_at = document_chunks.created_at
            RETURNING id
            """,
            (
                document_id,
                chunk.chunk_index,
                chunk.heading,
                chunk.content,
                chunk.page_number,
                Json({"source": "pdf_text_extraction"}),
                embedding_text,
                vector_to_pg(embedding),
            ),
        )
        row = cur.fetchone()
    conn.commit()
    return int(row["id"])
