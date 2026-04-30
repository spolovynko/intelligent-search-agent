from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from intelligent_search_agent.agent.assistant.lexicon import meaningful_query_terms
from intelligent_search_agent.agent.assistant.routing import AssistantRoute, asset_kind_filter
from intelligent_search_agent.core.config import get_settings

logger = logging.getLogger(__name__)


class RerankItem(BaseModel):
    ref: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class RerankResult(BaseModel):
    items: list[RerankItem] = Field(default_factory=list)


def asset_search_text(row: dict[str, Any]) -> str:
    metadata = row.get("metadata") or {}
    vlm = metadata.get("vlm_entry") or {}
    manifest = metadata.get("source_manifest") or {}
    parts = [
        row.get("file_name"),
        row.get("description"),
        row.get("asset_content"),
        row.get("document_content"),
        row.get("asset_kind"),
        row.get("period"),
        row.get("language"),
        manifest.get("title"),
        manifest.get("search_term"),
        " ".join(metadata.get("tags") or []),
        vlm.get("title"),
        " ".join(vlm.get("subjects") or []),
        " ".join(vlm.get("locations") or []),
        " ".join(vlm.get("people") or []),
        vlm.get("visual_style"),
        " ".join(vlm.get("search_keywords") or []),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def asset_rerank_score(row: dict[str, Any], query: str, route: AssistantRoute) -> float:
    base_score = float(row.get("similarity") or 0.0)
    terms = meaningful_query_terms(query)
    text = asset_search_text(row)
    score = base_score

    if terms:
        overlap = sum(1 for term in terms if term in text)
        score += min(0.20, 0.035 * overlap)

    for phrase in re.findall(r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)+", query):
        if phrase.lower() in text:
            score += 0.08

    filtered_kind = asset_kind_filter(query, route)
    if filtered_kind and row.get("asset_kind") == filtered_kind:
        score += 0.12
    elif row.get("asset_kind") in {"painting", "illustration", "map", "photo", "document_scan"}:
        score += 0.03

    if row.get("source_url"):
        score += 0.01

    return min(score, 1.0)


def rerank_asset_rows(
    rows: list[dict[str, Any]],
    query: str,
    route: AssistantRoute,
    limit: int,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["retrieval_score"] = row.get("similarity")
        item["rerank_score"] = asset_rerank_score(row, query, route)
        item["similarity"] = item["rerank_score"]
        ranked.append(item)

    ranked.sort(key=lambda item: item.get("rerank_score") or 0.0, reverse=True)
    return ranked[:limit]


def compact_finding_for_rerank(item: dict[str, Any]) -> str:
    if item.get("source") == "asset":
        metadata = item.get("metadata") or {}
        tags = metadata.get("tags") or []
        return " | ".join(
            [
                str(item.get("ref") or ""),
                "asset",
                str(item.get("title") or ""),
                str(item.get("asset_kind") or ""),
                str(item.get("period") or ""),
                str(item.get("summary") or "")[:360],
                f"tags: {', '.join(tags[:10])}" if isinstance(tags, list) else "",
            ]
        )
    return " | ".join(
        [
            str(item.get("ref") or ""),
            "document",
            str(item.get("citation") or item.get("title") or ""),
            str(item.get("heading") or ""),
            str(item.get("summary") or "")[:520],
        ]
    )


def apply_rerank_order(items: list[dict[str, Any]], rerank: RerankResult) -> list[dict[str, Any]]:
    by_ref = {item.get("ref"): item for item in items}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    for ranked in sorted(rerank.items, key=lambda item: item.score, reverse=True):
        item = by_ref.get(ranked.ref)
        if item and ranked.ref not in seen:
            updated = dict(item)
            updated["llm_rerank_score"] = ranked.score
            updated["llm_rerank_reason"] = ranked.reason
            ordered.append(updated)
            seen.add(ranked.ref)

    ordered.extend(item for item in items if item.get("ref") not in seen)
    return ordered


async def rerank_findings_with_llm(
    question: str,
    route: AssistantRoute,
    findings: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    settings = get_settings()
    if not settings.openai_api_key or not settings.llm_rerank_enabled:
        return findings

    try:
        reranker = Agent(
            settings.pydantic_ai_model_string,
            output_type=RerankResult,
            system_prompt=(
                "Rerank retrieved search results for a Belgian-history assistant. "
                "Return refs in best-to-worst order with a 0-1 relevance score. "
                "Prefer exact subject, event, location, period, and requested media-kind matches. "
                "Do not invent refs."
            ),
        )

        updated = {key: list(value) for key, value in findings.items()}
        for source_key in ("assets", "documents"):
            items = updated.get(source_key, [])
            if len(items) < 2:
                continue
            limited = items[: settings.llm_rerank_top_k]
            prompt = "\n".join(
                [
                    f"User request: {question}",
                    f"Route: {route.model_dump_json()}",
                    f"Result type: {source_key}",
                    "",
                    "Candidates:",
                    "\n".join(compact_finding_for_rerank(item) for item in limited),
                ]
            )
            result = await reranker.run(prompt, model_settings={"temperature": 0.0})
            updated[source_key] = apply_rerank_order(limited, result.output) + items[len(limited) :]
        return updated
    except Exception as exc:
        logger.warning("LLM reranking failed; keeping deterministic order: %s", exc)
        return findings


def serialize_asset(row: dict[str, Any], index: int) -> dict[str, Any]:
    asset_id = row.get("id")
    return {
        "ref": f"A{index}",
        "source": "asset",
        "id": asset_id,
        "title": row.get("file_name") or row.get("description"),
        "summary": row.get("description") or row.get("asset_content"),
        "asset_kind": row.get("asset_kind"),
        "period": row.get("period"),
        "language": row.get("language"),
        "score": row.get("similarity"),
        "retrieval_score": row.get("retrieval_score"),
        "rerank_score": row.get("rerank_score"),
        "preview_url": f"/v1/assets/{asset_id}/file" if asset_id else None,
        "download_url": f"/v1/assets/{asset_id}/file?download=true" if asset_id else None,
        "detail_url": f"/v1/assets/{asset_id}" if asset_id else None,
        "source_url": row.get("source_url"),
        "metadata": row.get("metadata") or {},
    }


def serialize_document(row: dict[str, Any], index: int) -> dict[str, Any]:
    document_id = row.get("document_id")
    page_number = row.get("page_number")
    title = row.get("document_title")
    page_label = f"p. {page_number}" if page_number else "page unknown"
    open_url = f"/v1/documents/{document_id}/file" if document_id else row.get("source_uri")
    if open_url and page_number:
        open_url = f"{open_url}#page={page_number}"
    return {
        "ref": f"D{index}",
        "source": "document",
        "id": row.get("id"),
        "document_id": document_id,
        "title": title,
        "summary": row.get("content"),
        "heading": row.get("heading"),
        "page_number": page_number,
        "doc_type": row.get("doc_type"),
        "language": row.get("language"),
        "score": row.get("similarity"),
        "source_url": row.get("source_uri"),
        "detail_url": f"/v1/documents/{document_id}" if document_id else None,
        "open_url": open_url,
        "citation": f"{title or 'Document'} ({page_label})",
        "metadata": row.get("metadata") or {},
    }


def findings_context(findings: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    for item in findings.get("assets", []):
        lines.append(
            " | ".join(
                [
                    item["ref"],
                    "asset",
                    str(item.get("title") or ""),
                    str(item.get("asset_kind") or ""),
                    str(item.get("period") or ""),
                    str(item.get("summary") or "")[:450],
                ]
            )
        )
    for item in findings.get("documents", []):
        lines.append(
            " | ".join(
                [
                    item["ref"],
                    "document",
                    str(item.get("citation") or item.get("title") or ""),
                    f"page {item.get('page_number') or ''}",
                    str(item.get("summary") or "")[:650],
                    str(item.get("source_url") or ""),
                ]
            )
        )
    return "\n".join(lines)
