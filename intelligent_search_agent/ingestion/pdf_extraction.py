from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from intelligent_search_agent.ingestion.common import normalize_text


@dataclass
class PdfChunk:
    chunk_index: int
    page_number: int
    content: str
    heading: str | None = None


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
        raise RuntimeError(
            "PyMuPDF is required for PDF ingestion. Install with pip install pymupdf."
        ) from exc

    if pdf_ocr not in {"auto", "on", "off"}:
        raise ValueError("pdf_ocr must be one of: auto, on, off")

    chunks: list[PdfChunk] = []
    ocr_engine = get_ocr_engine(required=pdf_ocr == "on") if pdf_ocr != "off" else None
    ocr_unavailable = pdf_ocr != "off" and ocr_engine is None
    with fitz.open(pdf_path) as document:
        metadata = {
            "page_count": document.page_count,
            "pdf_metadata": {
                key: value for key, value in (document.metadata or {}).items() if value
            },
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
