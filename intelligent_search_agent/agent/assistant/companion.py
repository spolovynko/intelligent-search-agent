from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Sequence
from typing import Any
from uuid import uuid4

from intelligent_search_agent.agent.assistant.answering import fallback_answer, stream_answer
from intelligent_search_agent.agent.assistant.conversation import (
    contextual_question,
    last_user_question,
    looks_like_followup,
    recent_history_lines,
)
from intelligent_search_agent.agent.assistant.events import sse
from intelligent_search_agent.agent.assistant.findings import (
    RerankItem,
    RerankResult,
    apply_rerank_order,
    asset_rerank_score,
    asset_search_text,
    compact_finding_for_rerank,
    findings_context,
    rerank_asset_rows,
    rerank_findings_with_llm,
    serialize_asset,
    serialize_document,
)
from intelligent_search_agent.agent.assistant.lexicon import (
    ASSET_KIND_ALIASES,
    ASSET_KIND_VALUES,
    DOCUMENT_TERMS,
    FOLLOWUP_TERMS,
    HISTORY_TERMS,
    IMAGE_TERMS,
    MIXED_TERMS,
    QUESTION_TERMS,
    STOPWORDS,
    meaningful_query_terms,
    tokens,
)
from intelligent_search_agent.agent.assistant.routing import (
    AssistantIntent,
    AssistantRoute,
    ROUTER_PROMPT,
    apply_user_intent_overrides,
    asset_kind_filter,
    choose_sources,
    heuristic_route,
    normalize_route,
    route_request,
)
from intelligent_search_agent.core.config import get_settings
from intelligent_search_agent.db import Database

logger = logging.getLogger(__name__)

_sse = sse
_tokens = tokens


async def persist_session_history(
    db: Database,
    *,
    session_id: str,
    question: str,
    messages: Sequence[Any] | None,
) -> Sequence[Any] | None:
    try:
        await db.chat.ensure_session(
            session_id,
            title=question[:100],
            metadata={"client": "companion"},
        )
        if messages:
            return messages
        return await db.chat.recent_messages(session_id, limit=10)
    except Exception as exc:
        logger.warning("Chat session persistence unavailable: %s", exc)
        return messages


async def persist_turn(
    db: Database,
    *,
    session_id: str,
    question: str,
    effective_question: str,
    answer_text: str,
    route: AssistantRoute,
    findings: dict[str, list[dict[str, Any]]],
) -> None:
    try:
        await db.chat.append_message(
            session_id,
            "user",
            question,
            metadata={
                "effective_question": effective_question,
                "route": route.model_dump(mode="json"),
            },
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


def search_status_message(route: AssistantRoute) -> str | None:
    if route.needs_assets and route.needs_documents:
        return "Searching images and PDF evidence..."
    if route.needs_assets:
        return "Searching image assets..."
    if route.needs_documents:
        return "Searching PDF evidence..."
    return None


async def collect_findings(
    db: Database,
    *,
    question: str,
    effective_question: str,
    search_query: str,
    route: AssistantRoute,
    limit: int,
) -> dict[str, list[dict[str, Any]]]:
    findings: dict[str, list[dict[str, Any]]] = {"assets": [], "documents": []}

    if route.needs_assets:
        desired_asset_count = max(limit, 10) if route.display_mode == "mixed" else limit
        candidate_count = max(desired_asset_count * 3, 24)
        asset_rows = await db.assets.search(
            effective_question,
            limit=candidate_count,
            asset_kind=asset_kind_filter(question, route),
            language=route.language,
            period=route.period,
        )
        asset_rows = rerank_asset_rows(
            asset_rows,
            effective_question,
            route,
            desired_asset_count,
        )
        findings["assets"] = [
            serialize_asset(row, index + 1) for index, row in enumerate(asset_rows)
        ]

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

    return findings


async def companion_stream(
    question: str,
    limit: int = 8,
    messages: Sequence[Any] | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    start = time.perf_counter()
    settings = get_settings()
    session_id = session_id or str(uuid4())
    db = Database()

    yield sse({"type": "status", "message": "Planning request..."})
    yield sse({"type": "session", "session_id": session_id})

    try:
        history_messages = (
            await persist_session_history(
                db,
                session_id=session_id,
                question=question,
                messages=messages,
            )
            if settings.persist_chat_sessions
            else messages
        )

        effective_question = contextual_question(question, history_messages)
        route = await route_request(question, history_messages)
        search_query = route.search_query or effective_question
        yield sse(
            {
                "type": "route",
                "route": route.model_dump(mode="json"),
                "memory": {
                    "used": effective_question != question,
                    "effective_question": effective_question,
                },
            }
        )

        status = search_status_message(route)
        if status:
            yield sse({"type": "status", "message": status})

        findings = await collect_findings(
            db,
            question=question,
            effective_question=effective_question,
            search_query=search_query,
            route=route,
            limit=limit,
        )

        yield sse({"type": "findings", "mode": route.display_mode, "findings": findings})
        if settings.llm_rerank_enabled and (
            len(findings["assets"]) > 1 or len(findings["documents"]) > 1
        ):
            yield sse({"type": "status", "message": "Reranking findings..."})
            findings = await rerank_findings_with_llm(effective_question, route, findings)
            yield sse({"type": "findings", "mode": route.display_mode, "findings": findings})

        yield sse({"type": "status", "message": "Writing answer..."})
        answer_parts: list[str] = []
        async for chunk in stream_answer(
            question, effective_question, history_messages, findings, route
        ):
            answer_parts.append(chunk)
            yield sse({"type": "chunk", "content": chunk})

        answer_text = "".join(answer_parts).strip()
        if settings.persist_chat_sessions:
            await persist_turn(
                db,
                session_id=session_id,
                question=question,
                effective_question=effective_question,
                answer_text=answer_text,
                route=route,
                findings=findings,
            )

        yield sse(
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
        yield sse({"type": "error", "message": str(exc)})


__all__ = [
    "ASSET_KIND_ALIASES",
    "ASSET_KIND_VALUES",
    "AssistantIntent",
    "AssistantRoute",
    "DOCUMENT_TERMS",
    "FOLLOWUP_TERMS",
    "HISTORY_TERMS",
    "IMAGE_TERMS",
    "MIXED_TERMS",
    "QUESTION_TERMS",
    "ROUTER_PROMPT",
    "RerankItem",
    "RerankResult",
    "STOPWORDS",
    "apply_rerank_order",
    "apply_user_intent_overrides",
    "asset_kind_filter",
    "asset_rerank_score",
    "asset_search_text",
    "choose_sources",
    "compact_finding_for_rerank",
    "companion_stream",
    "contextual_question",
    "fallback_answer",
    "findings_context",
    "heuristic_route",
    "last_user_question",
    "looks_like_followup",
    "meaningful_query_terms",
    "normalize_route",
    "recent_history_lines",
    "rerank_asset_rows",
    "rerank_findings_with_llm",
    "route_request",
    "serialize_asset",
    "serialize_document",
    "stream_answer",
    "tokens",
]
