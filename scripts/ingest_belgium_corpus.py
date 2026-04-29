from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from intelligent_search_agent.ingestion.corpus_ingest import (  # noqa: E402
    DEFAULT_MANIFEST,
    DEFAULT_PROJECT_EXTERNAL_ID,
    DEFAULT_PROJECT_NAME,
    DEFAULT_VLM_CACHE,
    IngestOptions,
    run_ingestion,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create VLM image entries, embed PDFs, and upsert the Belgium corpus into PostgreSQL."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--vlm-cache", type=Path, default=DEFAULT_VLM_CACHE)
    parser.add_argument("--image-limit", type=int, default=None)
    parser.add_argument("--pdf-limit", type=int, default=None)
    parser.add_argument("--skip-images", action="store_true")
    parser.add_argument("--skip-pdfs", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Inspect local files/chunks without OpenAI or DB writes.")
    parser.add_argument("--force", action="store_true", help="Refresh rows even when they already exist.")
    parser.add_argument("--refresh-vlm", action="store_true", help="Ignore cached VLM entries and call the VLM again.")
    parser.add_argument("--apply-schema", action="store_true", help="Run sql/schema.sql before inserting.")
    parser.add_argument("--chunk-chars", type=int, default=4000)
    parser.add_argument("--chunk-overlap", type=int, default=500)
    parser.add_argument("--max-chunks-per-pdf", type=int, default=None)
    parser.add_argument(
        "--pdf-ocr",
        choices=["auto", "on", "off"],
        default="auto",
        help="OCR pages without embedded text. 'on' fails if OCR is unavailable.",
    )
    parser.add_argument("--ocr-languages", default="eng+fra+nld")
    parser.add_argument("--ocr-dpi", type=int, default=180)
    parser.add_argument("--retry-attempts", type=int, default=8)
    parser.add_argument("--project-external-id", default=DEFAULT_PROJECT_EXTERNAL_ID)
    parser.add_argument("--project-name", default=DEFAULT_PROJECT_NAME)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    options = IngestOptions(
        manifest_path=args.manifest,
        vlm_cache_path=args.vlm_cache,
        image_limit=args.image_limit,
        pdf_limit=args.pdf_limit,
        skip_images=args.skip_images,
        skip_pdfs=args.skip_pdfs,
        dry_run=args.dry_run,
        force=args.force,
        refresh_vlm=args.refresh_vlm,
        apply_schema=args.apply_schema,
        chunk_chars=args.chunk_chars,
        chunk_overlap=args.chunk_overlap,
        max_chunks_per_pdf=args.max_chunks_per_pdf,
        pdf_ocr=args.pdf_ocr,
        ocr_languages=args.ocr_languages,
        ocr_dpi=args.ocr_dpi,
        retry_attempts=args.retry_attempts,
        project_external_id=args.project_external_id,
        project_name=args.project_name,
    )
    stats = run_ingestion(options)
    print("")
    print("Ingestion summary")
    print(f"images seen: {stats.images_seen}")
    print(f"images inserted: {stats.images_inserted}")
    print(f"images skipped: {stats.images_skipped}")
    print(f"pdfs seen: {stats.pdfs_seen}")
    print(f"pdfs inserted: {stats.pdfs_inserted}")
    print(f"pdfs skipped: {stats.pdfs_skipped}")
    print(f"chunks planned: {stats.chunks_planned}")
    print(f"chunks inserted: {stats.chunks_inserted}")


if __name__ == "__main__":
    main()
