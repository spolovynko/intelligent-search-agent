from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncGenerator, Sequence
from enum import Enum
from typing import Any
from typing import Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_ai import Agent

from intelligent_search_agent.core.config import get_settings
from intelligent_search_agent.db import Database

logger = logging.getLogger(__name__)

IMAGE_TERMS = {
    "asset",
    "assets",
    "image",
    "images",
    "photo",
    "photos",
    "picture",
    "pictures",
    "painting",
    "paintings",
    "visual",
    "visuals",
    "map",
    "maps",
    "poster",
    "posters",
}

DOCUMENT_TERMS = {
    "article",
    "articles",
    "document",
    "documents",
    "pdf",
    "pdfs",
    "paper",
    "papers",
    "source",
    "sources",
    "text",
    "write",
    "explain",
    "summarize",
}

HISTORY_TERMS = {
    "antwerp",
    "belgian",
    "belgium",
    "brabant",
    "brussels",
    "dutch",
    "flanders",
    "flemish",
    "french",
    "ghent",
    "happened",
    "history",
    "independence",
    "patriotism",
    "revolution",
    "wallonia",
}

QUESTION_TERMS = {"how", "what", "when", "where", "why", "who"}
MIXED_TERMS = {"and", "also", "with", "alongside", "together"}

ASSET_KIND_VALUES = {
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

STOPWORDS = {
    "a",
    "about",
    "and",
    "are",
    "can",
    "connected",
    "for",
    "from",
    "give",
    "i",
    "in",
    "it",
    "me",
    "more",
    "of",
    "on",
    "only",
    "please",
    "related",
    "same",
    "show",
    "the",
    "them",
    "to",
    "too",
    "what",
    "with",
    "you",
}

FOLLOWUP_TERMS = {
    "also",
    "another",
    "just",
    "more",
    "only",
    "same",
    "similar",
    "them",
    "these",
    "those",
    "too",
}

ASSET_KIND_ALIASES = {
    "photo": {"photo", "photos", "picture", "pictures"},
    "painting": {"painting", "paintings"},
    "illustration": {"illustration", "illustrations"},
    "map": {"map", "maps"},
    "document_scan": {"scan", "scans", "document", "documents", "tract", "tracts"},
    "poster": {"poster", "posters"},
    "architecture": {"architecture", "building", "buildings"},
    "object": {"object", "objects", "artifact", "artifacts"},
}

ROUTER_PROMPT = """
Classify one user request for a local Belgian-history search assistant.

Return a structured route only. Do not answer the user's question.

Use these rules:
- image_search: the user mainly wants visual/image/asset results such as images, photos, maps,
  paintings, posters, illustrations, architecture, objects, or other visible assets.
- document_answer: the user mainly wants a prose answer grounded in PDF/document chunks.
- mixed_search: the user asks for both a prose answer/evidence/sources and visual assets.
- general_chat: the user is greeting, asking about the app, or asking something that should not
  search the corpus.

For Belgian historical questions that do not explicitly ask for images, prefer document_answer.
For requests that say "show" but do not name a visual asset type, do not infer image_search.
Make search_query short and suitable for semantic retrieval.
Only set asset_kind when the user clearly asks for one of the allowed values.
Allowed asset_kind values: photo, painting, illustration, map, document_scan, poster,
architecture, object, other.
""".strip()


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]+", text.lower()))


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(getattr(message, "role", "") or "")


def recent_history_lines(messages: Sequence[Any] | None, limit: int = 6) -> list[str]:
    if not messages:
        return []

    lines: list[str] = []
    for message in messages[-limit:]:
        role = _message_role(message)
        content = re.sub(r"\s+", " ", _message_content(message)).strip()
        if role in {"user", "assistant"} and content:
            lines.append(f"{role}: {content[:500]}")
    return lines


def last_user_question(messages: Sequence[Any] | None) -> str | None:
    if not messages:
        return None
    for message in reversed(messages):
        if _message_role(message) == "user":
            content = re.sub(r"\s+", " ", _message_content(message)).strip()
            if content:
                return content
    return None


def looks_like_followup(question: str) -> bool:
    tokens = _tokens(question)
    if not tokens:
        return False
    if tokens & FOLLOWUP_TERMS:
        return True
    if len(tokens) <= 4 and tokens & (IMAGE_TERMS | DOCUMENT_TERMS | set().union(*ASSET_KIND_ALIASES.values())):
        return True
    return bool(tokens & {"it", "that", "them", "those", "these"})


def contextual_question(question: str, messages: Sequence[Any] | None) -> str:
    previous = last_user_question(messages)
    if not previous or not looks_like_followup(question):
        return question
    return f"{previous}. Follow-up constraint: {question}"


class AssistantIntent(str, Enum):
    IMAGE_SEARCH = "image_search"
    DOCUMENT_ANSWER = "document_answer"
    MIXED_SEARCH = "mixed_search"
    GENERAL_CHAT = "general_chat"


class AssistantRoute(BaseModel):
    intent: AssistantIntent = Field(
        description="The high-level action the assistant should take for this user request."
    )
    search_query: str = Field(
        default="",
        description="Short semantic search query to use for retrieval. Leave empty only for general chat."
    )
    needs_assets: bool = False
    needs_documents: bool = False
    display_mode: Literal["chat", "asset_table", "mixed"] = "chat"
    asset_kind: Literal[
        "photo",
        "painting",
        "illustration",
        "map",
        "document_scan",
        "poster",
        "architecture",
        "object",
        "other",
    ] | None = None
    language: str | None = None
    period: str | None = None
    doc_type: str | None = None
    answer_focus: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("search_query", "answer_focus", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> str:
        if value is None:
            return ""
        return re.sub(r"\s+", " ", str(value)).strip()

    @field_validator("language", "period", "doc_type", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = re.sub(r"\s+", " ", str(value)).strip()
        return text or None

    @model_validator(mode="after")
    def normalize_route(self) -> "AssistantRoute":
        if self.intent == AssistantIntent.IMAGE_SEARCH:
            self.needs_assets = True
            self.needs_documents = False
        elif self.intent == AssistantIntent.DOCUMENT_ANSWER:
            self.needs_assets = False
            self.needs_documents = True
        elif self.intent == AssistantIntent.MIXED_SEARCH:
            self.needs_assets = True
            self.needs_documents = True
        elif self.intent == AssistantIntent.GENERAL_CHAT:
            self.needs_assets = False
            self.needs_documents = False

        if self.needs_assets and self.needs_documents:
            self.display_mode = "mixed"
        elif self.needs_assets:
            self.display_mode = "asset_table"
        else:
            self.display_mode = "chat"

        return self


class RerankItem(BaseModel):
    ref: str
    score: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class RerankResult(BaseModel):
    items: list[RerankItem] = Field(default_factory=list)


def normalize_route(route: AssistantRoute, question: str) -> AssistantRoute:
    if route.intent != AssistantIntent.GENERAL_CHAT and not route.search_query:
        route.search_query = question
    return route.model_validate(route.model_dump())


def apply_user_intent_overrides(route: AssistantRoute, question: str) -> AssistantRoute:
    tokens = _tokens(question)
    explicit_assets = bool(tokens & IMAGE_TERMS)
    explicit_answer = bool(tokens & (DOCUMENT_TERMS | QUESTION_TERMS))
    history_question = bool(tokens & HISTORY_TERMS) and bool(tokens & (QUESTION_TERMS | DOCUMENT_TERMS))

    if explicit_assets and explicit_answer:
        route.intent = AssistantIntent.MIXED_SEARCH
    elif explicit_assets:
        route.intent = AssistantIntent.IMAGE_SEARCH
    elif not explicit_assets and route.intent == AssistantIntent.IMAGE_SEARCH:
        route.intent = AssistantIntent.DOCUMENT_ANSWER if history_question else AssistantIntent.GENERAL_CHAT

    return normalize_route(route, question)


def heuristic_route(question: str) -> AssistantRoute:
    tokens = _tokens(question)
    wants_assets = bool(tokens & IMAGE_TERMS)
    wants_documents = bool(tokens & (DOCUMENT_TERMS | HISTORY_TERMS | QUESTION_TERMS))
    wants_mixed = wants_assets and bool(tokens & (DOCUMENT_TERMS | MIXED_TERMS))

    if wants_mixed:
        intent = AssistantIntent.MIXED_SEARCH
    elif wants_assets:
        intent = AssistantIntent.IMAGE_SEARCH
    elif wants_documents:
        intent = AssistantIntent.DOCUMENT_ANSWER
    else:
        intent = AssistantIntent.GENERAL_CHAT

    asset_kind = next((item for item in sorted(ASSET_KIND_VALUES) if item in tokens), None)
    return apply_user_intent_overrides(
        AssistantRoute(
            intent=intent,
            search_query=question if intent != AssistantIntent.GENERAL_CHAT else "",
            needs_assets=intent in {AssistantIntent.IMAGE_SEARCH, AssistantIntent.MIXED_SEARCH},
            needs_documents=intent in {AssistantIntent.DOCUMENT_ANSWER, AssistantIntent.MIXED_SEARCH},
            asset_kind=asset_kind,
            confidence=0.45,
        ),
        question,
    )


def asset_kind_filter(question: str, route: AssistantRoute) -> str | None:
    if not route.asset_kind or route.asset_kind == "other":
        return None

    tokens = _tokens(question)
    return route.asset_kind if tokens & ASSET_KIND_ALIASES.get(route.asset_kind, set()) else None


async def route_request(question: str, messages: Sequence[Any] | None = None) -> AssistantRoute:
    settings = get_settings()
    effective_question = contextual_question(question, messages)
    fallback = heuristic_route(effective_question)
    if not settings.openai_api_key:
        return fallback

    try:
        history = "\n".join(recent_history_lines(messages))
        prompt = (
            f"Recent conversation:\n{history or '(none)'}\n\n"
            f"Current user request:\n{question}\n\n"
            f"Resolved request for retrieval:\n{effective_question}"
        )
        router = Agent(
            settings.pydantic_ai_model_string,
            output_type=AssistantRoute,
            system_prompt=ROUTER_PROMPT,
        )
        result = await router.run(
            prompt,
            model_settings={"temperature": 0.0},
        )
        return apply_user_intent_overrides(result.output, effective_question)
    except Exception as exc:
        logger.warning("Structured request routing failed; using heuristic route: %s", exc)
        return fallback


def choose_sources(question: str) -> tuple[bool, bool]:
    route = heuristic_route(question)
    return route.needs_assets, route.needs_documents


def meaningful_query_terms(text: str) -> set[str]:
    return {token for token in _tokens(text) if len(token) > 2 and token not in STOPWORDS}


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


def fallback_answer(
    question: str,
    findings: dict[str, list[dict[str, Any]]],
    route: AssistantRoute | None = None,
) -> str:
    if route and route.intent == AssistantIntent.GENERAL_CHAT:
        return (
            "I can help search the local Belgian-history PDFs and image assets. "
            "Ask for a history answer, images, maps, paintings, or both."
        )
    asset_count = len(findings.get("assets", []))
    doc_count = len(findings.get("documents", []))
    if asset_count and not doc_count:
        top = findings["assets"][0]
        return (
            f"I found {asset_count} visual matches for your request. "
            f"The strongest match is [{top['ref']}] {top.get('title')}, "
            f"which is described as {top.get('summary')}."
        )
    if doc_count and not asset_count:
        top = findings["documents"][0]
        return (
            f"I found {doc_count} document chunks related to your question. The strongest match is "
            f"[{top['ref']}] {top.get('citation') or top.get('title')}."
        )
    if asset_count or doc_count:
        return f"I found {asset_count} visual matches and {doc_count} document matches for: {question}"
    return f"I could not find matching corpus items for: {question}"


async def stream_answer(
    question: str,
    effective_question: str,
    messages: Sequence[Any] | None,
    findings: dict[str, list[dict[str, Any]]],
    route: AssistantRoute,
) -> AsyncGenerator[str, None]:
    settings = get_settings()
    if not settings.openai_api_key:
        yield fallback_answer(question, findings, route)
        return

    base_url = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
    context = findings_context(findings)
    history = "\n".join(recent_history_lines(messages, limit=6))
    if route.display_mode == "asset_table":
        mode_instruction = (
            "The UI is showing an image findings table with Show buttons. Briefly explain what "
            "the table contains and refer to image rows by refs like [A1]. Do not include "
            "markdown tables or URLs in the prose."
        )
    elif route.display_mode == "mixed":
        mode_instruction = (
            "The UI is showing an image findings table and clickable document source chips. "
            "Answer the user's historical question in prose using document refs like [D1], "
            "and mention the best image rows by refs like [A1]. Do not include markdown tables or URLs."
        )
    elif route.intent == AssistantIntent.GENERAL_CHAT:
        mode_instruction = (
            "No corpus retrieval was needed. Answer conversationally and briefly. If useful, "
            "say that you can search Belgian-history PDFs and image assets."
        )
    else:
        mode_instruction = (
            "The UI is not showing an image table. Answer in prose in the chat. Ground claims "
            "in document findings and cite refs like [D1] when useful. Do not include markdown tables or URLs."
        )

    messages = [
        {
            "role": "system",
            "content": (
                "You are an assistant for a visual and document search corpus. "
                "For corpus questions, answer from the supplied findings only. "
                f"{mode_instruction} "
                "Do not invent URLs or markdown links. Keep the answer concise."
            ),
        },
        {
            "role": "user",
            "content": (
                f"User question: {question}\n\n"
                f"Resolved retrieval question: {effective_question}\n\n"
                f"Recent conversation:\n{history or '(none)'}\n\n"
                f"Assistant route: {route.model_dump_json()}\n\n"
                f"Retrieved findings:\n{context or 'No findings.'}\n\n"
                "Write the response for the user."
            ),
        },
    ]

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.2,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        break
                    data = json.loads(payload)
                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content")
                    if delta:
                        yield delta
    except Exception as exc:
        logger.warning("Companion answer stream failed: %s", exc)
        yield fallback_answer(question, findings, route)


async def companion_stream(
    question: str,
    limit: int = 8,
    messages: Sequence[Any] | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    start = time.perf_counter()
    settings = get_settings()
    session_id = session_id or str(uuid4())
    yield _sse({"type": "status", "message": "Planning request..."})
    yield _sse({"type": "session", "session_id": session_id})

    db = Database()
    history_messages: Sequence[Any] | None = messages
    findings: dict[str, list[dict[str, Any]]] = {"assets": [], "documents": []}

    try:
        if settings.persist_chat_sessions:
            try:
                await db.chat.ensure_session(
                    session_id,
                    title=question[:100],
                    metadata={"client": "companion"},
                )
                if not history_messages:
                    history_messages = await db.chat.recent_messages(session_id, limit=10)
            except Exception as exc:
                logger.warning("Chat session persistence unavailable: %s", exc)

        effective_question = contextual_question(question, history_messages)
        route = await route_request(question, history_messages)
        search_query = route.search_query or effective_question
        yield _sse(
            {
                "type": "route",
                "route": route.model_dump(mode="json"),
                "memory": {
                    "used": effective_question != question,
                    "effective_question": effective_question,
                },
            }
        )

        if route.needs_assets and route.needs_documents:
            yield _sse({"type": "status", "message": "Searching images and PDF evidence..."})
        elif route.needs_assets:
            yield _sse({"type": "status", "message": "Searching image assets..."})
        elif route.needs_documents:
            yield _sse({"type": "status", "message": "Searching PDF evidence..."})

        if route.needs_assets:
            asset_search_query = effective_question
            desired_asset_count = max(limit, 10) if route.display_mode == "mixed" else limit
            candidate_count = max(desired_asset_count * 3, 24)
            asset_rows = await db.assets.search(
                asset_search_query,
                limit=candidate_count,
                asset_kind=asset_kind_filter(question, route),
                language=route.language,
                period=route.period,
            )
            asset_rows = rerank_asset_rows(
                asset_rows,
                asset_search_query,
                route,
                desired_asset_count,
            )
            findings["assets"] = [serialize_asset(row, index + 1) for index, row in enumerate(asset_rows)]

        if route.needs_documents:
            doc_limit = max(4, min(limit, 8))
            doc_rows = await db.documents.search(
                search_query,
                limit=doc_limit,
                doc_type=route.doc_type,
                language=route.language,
            )
            findings["documents"] = [
                serialize_document(row, index + 1) for index, row in enumerate(doc_rows)
            ]

        yield _sse({"type": "findings", "mode": route.display_mode, "findings": findings})
        if settings.llm_rerank_enabled and (len(findings["assets"]) > 1 or len(findings["documents"]) > 1):
            yield _sse({"type": "status", "message": "Reranking findings..."})
            findings = await rerank_findings_with_llm(effective_question, route, findings)
            yield _sse({"type": "findings", "mode": route.display_mode, "findings": findings})
        yield _sse({"type": "status", "message": "Writing answer..."})

        answer_parts: list[str] = []
        async for chunk in stream_answer(question, effective_question, history_messages, findings, route):
            answer_parts.append(chunk)
            yield _sse({"type": "chunk", "content": chunk})

        answer_text = "".join(answer_parts).strip()
        if settings.persist_chat_sessions:
            try:
                await db.chat.append_message(
                    session_id,
                    "user",
                    question,
                    metadata={"effective_question": effective_question, "route": route.model_dump(mode="json")},
                )
                await db.chat.append_message(
                    session_id,
                    "assistant",
                    answer_text,
                    metadata={
                        "mode": route.display_mode,
                        "counts": {
                            "assets": len(findings["assets"]),
                            "documents": len(findings["documents"]),
                        },
                    },
                )
            except Exception as exc:
                logger.warning("Could not persist chat messages: %s", exc)

        yield _sse(
            {
                "type": "done",
                "counts": {
                    "assets": len(findings["assets"]),
                    "documents": len(findings["documents"]),
                },
                "mode": route.display_mode,
                "session_id": session_id,
                "route": route.model_dump(mode="json"),
                "performance": {"total_ms": round((time.perf_counter() - start) * 1000, 1)},
            }
        )
    except Exception as exc:
        logger.exception("Companion stream failed")
        yield _sse({"type": "error", "message": str(exc)})
