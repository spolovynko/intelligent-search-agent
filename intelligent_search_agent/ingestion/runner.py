from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from intelligent_search_agent.core.config import Settings, get_settings
from intelligent_search_agent.db.embeddings import get_embedding_sync
from intelligent_search_agent.ingestion.common import (
    DEFAULT_MANIFEST,
    DEFAULT_PROJECT_EXTERNAL_ID,
    DEFAULT_PROJECT_NAME,
    load_corpus_manifest,
    normalize_text,
    resolve_local_path,
    retry_call,
    stable_external_id,
)
from intelligent_search_agent.ingestion.embedding_text import (
    compose_asset_embedding_text,
    compose_document_chunk_embedding_text,
)
from intelligent_search_agent.ingestion.image_analysis import (
    DEFAULT_VLM_CACHE,
    append_vlm_cache,
    describe_image_with_vlm,
    load_vlm_cache,
)
from intelligent_search_agent.ingestion.pdf_extraction import extract_pdf_chunks
from intelligent_search_agent.ingestion.repository import (
    apply_schema,
    asset_has_embedding,
    connect_db,
    delete_document_chunks,
    document_has_chunks,
    ensure_project,
    upsert_asset,
    upsert_document,
    upsert_document_chunk,
)


@dataclass
class IngestOptions:
    manifest_path: Path = DEFAULT_MANIFEST
    vlm_cache_path: Path = DEFAULT_VLM_CACHE
    image_limit: int | None = None
    pdf_limit: int | None = None
    skip_images: bool = False
    skip_pdfs: bool = False
    dry_run: bool = False
    force: bool = False
    refresh_vlm: bool = False
    apply_schema: bool = False
    chunk_chars: int = 4000
    chunk_overlap: int = 500
    max_chunks_per_pdf: int | None = None
    pdf_ocr: str = "auto"
    ocr_languages: str = "eng+fra+nld"
    ocr_dpi: int = 180
    retry_attempts: int = 8
    project_external_id: str = DEFAULT_PROJECT_EXTERNAL_ID
    project_name: str = DEFAULT_PROJECT_NAME


@dataclass
class IngestStats:
    images_seen: int = 0
    images_inserted: int = 0
    images_skipped: int = 0
    pdfs_seen: int = 0
    pdfs_inserted: int = 0
    pdfs_skipped: int = 0
    chunks_inserted: int = 0
    chunks_planned: int = 0


def limited_manifest_items(
    options: IngestOptions,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    images, pdfs = load_corpus_manifest(options.manifest_path)
    if options.image_limit is not None:
        images = images[: options.image_limit]
    if options.pdf_limit is not None:
        pdfs = pdfs[: options.pdf_limit]
    return images, pdfs


def run_dry_ingestion(
    *,
    options: IngestOptions,
    images: list[dict[str, Any]],
    pdfs: list[dict[str, Any]],
) -> IngestStats:
    stats = IngestStats()
    for item in images if not options.skip_images else []:
        stats.images_seen += 1
        if not resolve_local_path(item["local_path"]).exists():
            stats.images_skipped += 1
    for item in pdfs if not options.skip_pdfs else []:
        stats.pdfs_seen += 1
        chunks, metadata = extract_pdf_chunks(
            resolve_local_path(item["local_path"]),
            chunk_chars=options.chunk_chars,
            chunk_overlap=options.chunk_overlap,
            max_chunks=options.max_chunks_per_pdf,
            pdf_ocr=options.pdf_ocr,
            ocr_languages=options.ocr_languages,
            ocr_dpi=options.ocr_dpi,
        )
        if not chunks:
            stats.pdfs_skipped += 1
            if metadata.get("ocr_available") is False and options.pdf_ocr != "off":
                print(
                    "OCR unavailable; textless PDF produced no chunks: "
                    f"{Path(item['local_path']).name}"
                )
        stats.chunks_planned += len(chunks)
    return stats


def asset_embedding_text(item: dict[str, Any], entry, image_path: Path, project_name: str) -> str:
    return compose_asset_embedding_text(
        {
            "description": entry.description,
            "document_content": entry.ocr_text,
            "asset_content": ", ".join(
                entry.subjects + entry.locations + entry.people + entry.search_keywords
            ),
            "asset_kind": entry.asset_kind,
            "campaign_context": entry.campaign_context,
            "language": entry.language,
            "period": entry.period,
            "project_name": project_name,
            "file_name": image_path.name,
            "metadata": {
                "vlm_entry": entry.model_dump(exclude_none=True),
                "tags": sorted(
                    set(entry.subjects + entry.locations + entry.people + entry.search_keywords)
                ),
                "source_manifest": item,
            },
        }
    )


def ingest_images(
    *,
    conn,
    options: IngestOptions,
    settings: Settings,
    project_id: int,
    images: list[dict[str, Any]],
    stats: IngestStats,
) -> None:
    cache = load_vlm_cache(options.vlm_cache_path)
    for item in images:
        stats.images_seen += 1
        external_id = stable_external_id("commons", item)
        image_path = resolve_local_path(item["local_path"])
        if not image_path.exists():
            stats.images_skipped += 1
            print(f"skip missing image: {item.get('local_path')}")
            continue
        if not options.force and asset_has_embedding(conn, external_id):
            stats.images_skipped += 1
            continue

        entry = cache.get(external_id)
        if entry is None or options.refresh_vlm:
            entry = retry_call(
                f"VLM image {stats.images_seen}/{len(images)}",
                options.retry_attempts,
                lambda: describe_image_with_vlm(item, image_path, settings),
            )
            append_vlm_cache(options.vlm_cache_path, external_id, entry)
            cache[external_id] = entry

        embedding = retry_call(
            f"image embedding {stats.images_seen}/{len(images)}",
            options.retry_attempts,
            lambda: get_embedding_sync(
                asset_embedding_text(item, entry, image_path, options.project_name),
                settings=settings,
            ),
        )
        upsert_asset(
            conn,
            project_id=project_id,
            item=item,
            entry=entry,
            embedding=embedding,
            settings=settings,
            project_name=options.project_name,
        )
        stats.images_inserted += 1
        print(f"image {stats.images_seen}/{len(images)} ingested: {image_path.name}")


def ingest_pdfs(
    *,
    conn,
    options: IngestOptions,
    settings: Settings,
    pdfs: list[dict[str, Any]],
    stats: IngestStats,
) -> None:
    for item in pdfs:
        stats.pdfs_seen += 1
        external_id = stable_external_id("jbh", item)
        pdf_path = resolve_local_path(item["local_path"])
        if not pdf_path.exists():
            stats.pdfs_skipped += 1
            print(f"skip missing pdf: {item.get('local_path')}")
            continue
        if not options.force and document_has_chunks(conn, external_id):
            stats.pdfs_skipped += 1
            continue

        chunks, metadata = extract_pdf_chunks(
            pdf_path,
            chunk_chars=options.chunk_chars,
            chunk_overlap=options.chunk_overlap,
            max_chunks=options.max_chunks_per_pdf,
            pdf_ocr=options.pdf_ocr,
            ocr_languages=options.ocr_languages,
            ocr_dpi=options.ocr_dpi,
        )
        stats.chunks_planned += len(chunks)
        if not chunks:
            stats.pdfs_skipped += 1
            if metadata.get("ocr_available") is False and options.pdf_ocr != "off":
                print(
                    "OCR unavailable; textless PDF produced no chunks. "
                    "Install Tesseract locally or run inside Docker."
                )
            print(f"skip pdf with no extracted text: {pdf_path.name}")
            continue

        document_id = upsert_document(conn, item, metadata)
        if options.force:
            delete_document_chunks(conn, document_id)
        document_title = normalize_text(str(item.get("title") or pdf_path.name))
        for chunk in chunks:
            embedding_text = compose_document_chunk_embedding_text(
                {
                    "document_title": document_title,
                    "heading": chunk.heading,
                    "content": chunk.content,
                    "page_number": chunk.page_number,
                }
            )
            embedding = retry_call(
                f"pdf chunk embedding {stats.pdfs_seen}/{len(pdfs)}:{chunk.chunk_index}",
                options.retry_attempts,
                lambda: get_embedding_sync(embedding_text, settings=settings),
            )
            upsert_document_chunk(
                conn,
                document_id=document_id,
                document_title=document_title,
                chunk=chunk,
                embedding=embedding,
            )
            stats.chunks_inserted += 1
        stats.pdfs_inserted += 1
        print(f"pdf {stats.pdfs_seen}/{len(pdfs)} ingested: {pdf_path.name} ({len(chunks)} chunks)")


def run_ingestion(options: IngestOptions, settings: Settings | None = None) -> IngestStats:
    settings = settings or get_settings()
    images, pdfs = limited_manifest_items(options)

    if options.dry_run:
        return run_dry_ingestion(options=options, images=images, pdfs=pdfs)

    if not settings.openai_api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is required for ingestion embeddings and image VLM analysis."
        )

    stats = IngestStats()
    conn = connect_db(settings)
    try:
        if options.apply_schema:
            apply_schema(conn)
        project_id = ensure_project(conn, options.project_external_id, options.project_name)

        if not options.skip_images:
            ingest_images(
                conn=conn,
                options=options,
                settings=settings,
                project_id=project_id,
                images=images,
                stats=stats,
            )

        if not options.skip_pdfs:
            ingest_pdfs(conn=conn, options=options, settings=settings, pdfs=pdfs, stats=stats)
    finally:
        conn.close()

    return stats
