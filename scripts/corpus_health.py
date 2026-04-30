from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from intelligent_search_agent.core.config import PROJECT_ROOT, get_settings
from intelligent_search_agent.db import Database


def resolve_path(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    normalized = str(path).replace("\\", "/")
    if normalized.startswith("/app/storage/"):
        return PROJECT_ROOT / "storage" / normalized.removeprefix("/app/storage/")
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


async def collect_health(limit: int) -> dict[str, Any]:
    db = Database()
    counts = (
        await db.execute(
            """
        SELECT
            (SELECT COUNT(*) FROM assets) AS assets,
            (SELECT COUNT(*) FROM assets WHERE embedding IS NULL) AS assets_missing_embeddings,
            (SELECT COUNT(*) FROM documents) AS documents,
            (SELECT COUNT(*) FROM document_chunks) AS document_chunks,
            (SELECT COUNT(*) FROM document_chunks WHERE embedding IS NULL) AS chunks_missing_embeddings
        """
        )
    )[0]

    settings = get_settings()
    asset_rows = await db.execute(
        """
        SELECT id, file_name, file_path, storage_uri, content_hash
        FROM assets
        ORDER BY id
        LIMIT %s
        """,
        (limit,),
    )
    missing_assets = []
    for row in asset_rows:
        raw_path = row.get("file_path")
        if not raw_path and row.get("storage_uri"):
            raw_path = str(settings.asset_root / row["storage_uri"])
        path = resolve_path(raw_path)
        if not path or not path.exists():
            missing_assets.append({**row, "resolved_path": str(path or "")})

    duplicate_hashes = await db.execute(
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

    return {
        "counts": counts,
        "missing_assets_sample": missing_assets,
        "duplicate_hash_groups": duplicate_hashes,
    }


def print_summary(payload: dict[str, Any]) -> None:
    counts = payload["counts"]
    print("Corpus health")
    print(
        f"  assets: {counts['assets']} ({counts['assets_missing_embeddings']} missing embeddings)"
    )
    print(
        "  documents: "
        f"{counts['documents']} / chunks: {counts['document_chunks']} "
        f"({counts['chunks_missing_embeddings']} chunks missing embeddings)"
    )
    print(f"  missing local asset files in sample: {len(payload['missing_assets_sample'])}")
    print(f"  duplicate content hash groups: {len(payload['duplicate_hash_groups'])}")


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Inspect local corpus ingestion health.")
    parser.add_argument(
        "--limit", type=int, default=1000, help="Rows to inspect for local file checks."
    )
    parser.add_argument("--db-host", help="Override DB_HOST for this check.")
    parser.add_argument("--db-port", type=int, help="Override DB_PORT for this check.")
    parser.add_argument(
        "--docker-db",
        action="store_true",
        help="Use the default docker-compose host connection: localhost:5433.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    if args.docker_db:
        import os

        os.environ["DB_HOST"] = "localhost"
        os.environ["DB_PORT"] = "5433"
        get_settings.cache_clear()
    elif args.db_host or args.db_port:
        import os

        if args.db_host:
            os.environ["DB_HOST"] = args.db_host
        if args.db_port:
            os.environ["DB_PORT"] = str(args.db_port)
        get_settings.cache_clear()

    payload = await collect_health(args.limit)
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print_summary(payload)
    return 0


def main() -> int:
    import asyncio

    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
