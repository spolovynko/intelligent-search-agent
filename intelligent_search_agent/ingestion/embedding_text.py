from typing import Any


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list | tuple | set):
        return ", ".join(str(item) for item in value if item)
    return str(value).strip()


def compose_asset_embedding_text(asset: dict[str, Any]) -> str:
    metadata = asset.get("metadata") or {}
    vlm_entry = metadata.get("vlm_entry") or {}
    tags = metadata.get("tags") or []
    parts = [
        _clean(asset.get("description")),
        _clean(asset.get("document_content")),
        _clean(asset.get("asset_content")),
        _clean(vlm_entry.get("title")),
        _clean(vlm_entry.get("subjects")),
        _clean(vlm_entry.get("locations")),
        _clean(vlm_entry.get("people")),
        _clean(vlm_entry.get("visual_style")),
        _clean(vlm_entry.get("search_keywords")),
        _clean(tags),
        _clean(asset.get("asset_kind")),
        _clean(asset.get("campaign_context")),
        _clean(asset.get("language")),
        _clean(asset.get("period")),
        f"Project: {_clean(asset.get('project_name'))} ({_clean(asset.get('year'))})",
        f"File: {_clean(asset.get('file_name'))}",
    ]
    return ". ".join(part for part in parts if part)


def compose_document_chunk_embedding_text(chunk: dict[str, Any]) -> str:
    parts = [
        _clean(chunk.get("document_title")),
        _clean(chunk.get("heading")),
        _clean(chunk.get("content")),
        f"Page: {_clean(chunk.get('page_number'))}",
    ]
    return ". ".join(part for part in parts if part)


def compose_topic_embedding_text(topic: dict[str, Any]) -> str:
    parts = [
        _clean(topic.get("category")),
        _clean(topic.get("topic")),
        _clean(topic.get("content")),
        _clean(topic.get("responsible")),
        _clean(topic.get("status")),
    ]
    return ". ".join(part for part in parts if part)
