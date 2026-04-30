from __future__ import annotations

import json
import mimetypes
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, BinaryContent

from intelligent_search_agent.core.config import PROJECT_ROOT, Settings
from intelligent_search_agent.ingestion.common import normalize_text

DEFAULT_VLM_CACHE = PROJECT_ROOT / "storage" / "manifests" / "image_vlm_entries.jsonl"

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
            "Allowed asset_kind values: " + ", ".join(sorted(ALLOWED_ASSET_KINDS)),
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
