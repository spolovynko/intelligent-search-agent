from __future__ import annotations

import json
import mimetypes
import re
import time
from dataclasses import dataclass
from hashlib import sha1, sha256
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, BinaryContent

from intelligent_search_agent.core.config import PROJECT_ROOT, Settings, get_settings
from intelligent_search_agent.db.embeddings import get_embedding_sync, vector_to_pg
from intelligent_search_agent.ingestion.embedding_text import (
    compose_asset_embedding_text,
    compose_document_chunk_embedding_text,
)

DEFAULT_MANIFEST = PROJECT_ROOT / "storage" / "manifests" / "belgium_corpus_summary.json"
DEFAULT_VLM_CACHE = PROJECT_ROOT / "storage" / "manifests" / "image_vlm_entries.jsonl"
DEFAULT_PROJECT_EXTERNAL_ID = "belgian-history-corpus"
DEFAULT_PROJECT_NAME = "Belgian History Corpus"

IMAGE_SYSTEM_PROMPT = """
You create retrieval metadata for an image-search assistant.
Describe only what is visible or strongly supported by catalogue context.
Use English. Prefer broad historical periods over invented exact dates.
Put readable text in ocr_text when present; otherwise leave ocr_text null.
""".strip()

ALLOWED_ASSET_KINDS = {
    "photo",
    "painting",
    "illustration",
    "map",
    "document_scan",
    "poster",
    "architecture",
    "object",
    "other",
}

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


class ImageVlmEntry(BaseModel):
    title: str | None = None
    description: str = Field(min_length=20)
    asset_kind: str = "other"
    language: str | None = None
    period: str | None = None
    campaign_context: str = "belgian_history_corpus"
    subjects: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    visual_style: str | None = None
    ocr_text: str | None = None
    search_keywords: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("asset_kind", mode="before")
    @classmethod
    def normalize_asset_kind(cls, value: str | None) -> str:
        if not value:
            return "other"
        normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
        return normalized if normalized in ALLOWED_ASSET_KINDS else "other"

    @field_validator("subjects", "locations", "people", "search_keywords", mode="before")
    @classmethod
    def normalize_lists(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return [normalize_text(str(item)) for item in value if normalize_text(str(item))]

    @field_validator("title", "language", "period", "visual_style", "ocr_text", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = normalize_text(str(value))
        return text or None

    @field_validator("campaign_context", mode="before")
    @classmethod
    def normalize_campaign_context(cls, value: Any) -> str:
        text = normalize_text(str(value or "belgian_history_corpus"))
        return text or "belgian_history_corpus"


@dataclass
class PdfChunk:
    chunk_index: int
    page_number: int
    content: str
    heading: str | None = None


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


def normalize_text(value: str) -> str:
    text = unescape(HTML_TAG_RE.sub(" ", value))
    return WHITESPACE_RE.sub(" ", text).strip()


def is_retryable_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    retry_markers = [
        "429",
        "rate limit",
        "ratelimit",
        "timeout",
        "connection error",
        "temporarily unavailable",
        "server error",
        "503",
        "502",
        "500",
    ]
    return any(marker in text for marker in retry_markers)


def retry_call(label: str, attempts: int, func):
    last_error: Exception | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            return func()
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not is_retryable_error(exc):
                raise
            wait_seconds = min(60, 2 ** min(attempt, 5))
            print(
                f"{label} retry {attempt}/{attempts} after {type(exc).__name__}; "
                f"waiting {wait_seconds}s"
            )
            time.sleep(wait_seconds)
    if last_error:
        raise last_error
    raise RuntimeError(f"{label} failed without an exception")


def stable_external_id(prefix: str, item: dict[str, Any]) -> str:
    source = item.get("source_url") or item.get("download_url") or item.get("local_path") or item.get("title")
    digest = sha1(str(source).encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def resolve_local_path(local_path: str) -> Path:
    path = Path(local_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def storage_uri_for(path: Path, settings: Settings) -> str:
    try:
        return path.resolve().relative_to(settings.asset_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_corpus_manifest(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "images" in data and "pdfs" in data:
        return data["images"].get("items", []), data["pdfs"].get("items", [])
    return data.get("items", []), []


def load_vlm_cache(path: Path) -> dict[str, ImageVlmEntry]:
    if not path.exists():
        return {}

    cache: dict[str, ImageVlmEntry] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            cache[row["external_id"]] = ImageVlmEntry.model_validate(row["entry"])
    return cache


def append_vlm_cache(path: Path, external_id: str, entry: ImageVlmEntry) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {"external_id": external_id, "entry": entry.model_dump(exclude_none=True)},
                ensure_ascii=False,
            )
            + "\n"
        )


def build_image_prompt(item: dict[str, Any]) -> str:
    return "\n".join(
        [
            "Create a structured searchable record for this image.",
            "",
            "Allowed asset_kind values: "
            + ", ".join(sorted(ALLOWED_ASSET_KINDS)),
            "",
            "Catalogue context:",
            f"title: {normalize_text(str(item.get('title') or ''))}",
            f"source: {normalize_text(str(item.get('source') or ''))}",
            f"search_term: {normalize_text(str(item.get('search_term') or ''))}",
            f"artist: {normalize_text(str(item.get('artist') or ''))}",
            f"credit: {normalize_text(str(item.get('credit') or ''))}",
            f"license: {normalize_text(str(item.get('license') or ''))}",
        ]
    )


def describe_image_with_vlm(
    item: dict[str, Any],
    image_path: Path,
    settings: Settings,
) -> ImageVlmEntry:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for VLM image ingestion.")

    mime_type = item.get("mime") or mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    agent = Agent(
        f"openai:{settings.vision_model}",
        output_type=ImageVlmEntry,
        system_prompt=IMAGE_SYSTEM_PROMPT,
    )
    result = agent.run_sync(
        [
            build_image_prompt(item),
            BinaryContent(data=image_path.read_bytes(), media_type=mime_type),
        ],
        model_settings={"temperature": 0.1},
    )
    return result.output


def extract_pdf_chunks(
    pdf_path: Path,
    *,
    chunk_chars: int = 4000,
    chunk_overlap: int = 500,
    max_chunks: int | None = None,
    pdf_ocr: str = "auto",
    ocr_languages: str = "eng+fra+nld",
    ocr_dpi: int = 180,
) -> tuple[list[PdfChunk], dict[str, Any]]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF ingestion. Install with pip install pymupdf.") from exc

    if pdf_ocr not in {"auto", "on", "off"}:
        raise ValueError("pdf_ocr must be one of: auto, on, off")

    chunks: list[PdfChunk] = []
    ocr_engine = get_ocr_engine(required=pdf_ocr == "on") if pdf_ocr != "off" else None
    ocr_unavailable = pdf_ocr != "off" and ocr_engine is None
    with fitz.open(pdf_path) as document:
        metadata = {
            "page_count": document.page_count,
            "pdf_metadata": {k: v for k, v in (document.metadata or {}).items() if v},
            "ocr_mode": pdf_ocr,
            "ocr_languages": ocr_languages,
            "ocr_available": not ocr_unavailable,
        }
        for page_index, page in enumerate(document, start=1):
            page_text = normalize_text(page.get_text("text"))
            if len(page_text) < 40 and ocr_engine is not None:
                try:
                    page_text = normalize_text(ocr_page(page, ocr_engine, ocr_languages, ocr_dpi))
                except Exception as exc:
                    metadata.setdefault("ocr_errors", []).append(
                        {"page": page_index, "error": f"{type(exc).__name__}: {exc}"}
                    )
                    if pdf_ocr == "on":
                        raise
            if not page_text:
                continue
            for text in chunk_page_text(page_text, chunk_chars, chunk_overlap):
                chunks.append(
                    PdfChunk(
                        chunk_index=len(chunks),
                        page_number=page_index,
                        heading=heading_from_text(text),
                        content=text,
                    )
                )
                if max_chunks is not None and len(chunks) >= max_chunks:
                    return chunks, metadata
    return chunks, metadata


def get_ocr_engine(*, required: bool):
    try:
        import pytesseract
    except ImportError as exc:
        if required:
            raise RuntimeError("pytesseract is required when --pdf-ocr on is used.") from exc
        return None

    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:
        if required:
            raise RuntimeError(
                "Tesseract OCR executable is required when --pdf-ocr on is used."
            ) from exc
        return None
    return pytesseract


def ocr_page(page, pytesseract_module, languages: str, dpi: int) -> str:
    from PIL import Image

    pixmap = page.get_pixmap(dpi=dpi, alpha=False)
    image = Image.open(BytesIO(pixmap.tobytes("png")))
    try:
        return pytesseract_module.image_to_string(image, lang=languages)
    except Exception as exc:
        if languages != "eng" and "Failed loading language" in str(exc):
            return pytesseract_module.image_to_string(image, lang="eng")
        raise


def chunk_page_text(text: str, chunk_chars: int, overlap_chars: int) -> list[str]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be zero or positive")
    if overlap_chars >= chunk_chars:
        raise ValueError("chunk_overlap must be smaller than chunk_chars")

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            lower_bound = start + int(chunk_chars * 0.65)
            boundary = text.rfind(" ", lower_bound, end)
            if boundary > start:
                end = boundary

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def heading_from_text(text: str) -> str | None:
    words = text.split()
    if not words:
        return None
    return " ".join(words[:14])


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
        cur.execute("SELECT id FROM assets WHERE external_id = %s AND embedding IS NOT NULL", (external_id,))
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
    tags = sorted(set(entry.subjects + entry.locations + entry.people + entry.search_keywords))
    asset_content = ". ".join(
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
    metadata = {
        "source_manifest": item,
        "vlm_entry": entry.model_dump(exclude_none=True),
        "tags": tags,
        "image_analysis_model": settings.vision_model,
    }
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


def run_ingestion(options: IngestOptions, settings: Settings | None = None) -> IngestStats:
    settings = settings or get_settings()
    images, pdfs = load_corpus_manifest(options.manifest_path)
    if options.image_limit is not None:
        images = images[: options.image_limit]
    if options.pdf_limit is not None:
        pdfs = pdfs[: options.pdf_limit]

    stats = IngestStats()
    cache = load_vlm_cache(options.vlm_cache_path)

    if options.dry_run:
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

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required for ingestion embeddings and image VLM analysis.")

    conn = connect_db(settings)
    try:
        if options.apply_schema:
            apply_schema(conn)
        project_id = ensure_project(conn, options.project_external_id, options.project_name)

        if not options.skip_images:
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

                embedding_text = compose_asset_embedding_text(
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
                        "project_name": options.project_name,
                        "file_name": image_path.name,
                        "metadata": {
                            "vlm_entry": entry.model_dump(exclude_none=True),
                            "tags": sorted(
                                set(
                                    entry.subjects
                                    + entry.locations
                                    + entry.people
                                    + entry.search_keywords
                                )
                            ),
                        },
                    }
                )
                embedding = retry_call(
                    f"image embedding {stats.images_seen}/{len(images)}",
                    options.retry_attempts,
                    lambda: get_embedding_sync(embedding_text, settings=settings),
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

        if not options.skip_pdfs:
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
    finally:
        conn.close()

    return stats
