from __future__ import annotations

import json
import re
import time
from hashlib import sha1, sha256
from html import unescape
from pathlib import Path
from typing import Any, Callable, TypeVar

from intelligent_search_agent.core.config import PROJECT_ROOT, Settings

DEFAULT_MANIFEST = PROJECT_ROOT / "storage" / "manifests" / "belgium_corpus_summary.json"
DEFAULT_PROJECT_EXTERNAL_ID = "belgian-history-corpus"
DEFAULT_PROJECT_NAME = "Belgian History Corpus"

HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")

T = TypeVar("T")


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


def retry_call(label: str, attempts: int, func: Callable[[], T]) -> T:
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
    source = (
        item.get("source_url")
        or item.get("download_url")
        or item.get("local_path")
        or item.get("title")
    )
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
