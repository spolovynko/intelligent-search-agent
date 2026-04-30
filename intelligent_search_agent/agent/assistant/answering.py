from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator, Sequence
from typing import Any

import httpx

from intelligent_search_agent.agent.assistant.conversation import recent_history_lines
from intelligent_search_agent.agent.assistant.findings import findings_context
from intelligent_search_agent.agent.assistant.routing import AssistantIntent, AssistantRoute
from intelligent_search_agent.core.config import get_settings

logger = logging.getLogger(__name__)


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
        return (
            f"I found {asset_count} visual matches and {doc_count} document matches for: {question}"
        )
    return f"I could not find matching corpus items for: {question}"


def mode_instruction(route: AssistantRoute) -> str:
    if route.display_mode == "asset_table":
        return (
            "The UI is showing an image findings table with Show buttons. Briefly explain what "
            "the table contains and refer to image rows by refs like [A1]. Do not include "
            "markdown tables or URLs in the prose."
        )
    if route.display_mode == "mixed":
        return (
            "The UI is showing an image findings table and clickable document source chips. "
            "Answer the user's historical question in prose using document refs like [D1], "
            "and mention the best image rows by refs like [A1]. Do not include markdown tables or URLs."
        )
    if route.intent == AssistantIntent.GENERAL_CHAT:
        return (
            "No corpus retrieval was needed. Answer conversationally and briefly. If useful, "
            "say that you can search Belgian-history PDFs and image assets."
        )
    return (
        "The UI is not showing an image table. Answer in prose in the chat. Ground claims "
        "in document findings and cite refs like [D1] when useful. Do not include markdown tables or URLs."
    )


def answer_messages(
    *,
    question: str,
    effective_question: str,
    messages: Sequence[Any] | None,
    findings: dict[str, list[dict[str, Any]]],
    route: AssistantRoute,
) -> list[dict[str, str]]:
    context = findings_context(findings)
    history = "\n".join(recent_history_lines(messages, limit=6))
    return [
        {
            "role": "system",
            "content": (
                "You are an assistant for a visual and document search corpus. "
                "For corpus questions, answer from the supplied findings only. "
                f"{mode_instruction(route)} "
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
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.openai_model,
                    "messages": answer_messages(
                        question=question,
                        effective_question=effective_question,
                        messages=messages,
                        findings=findings,
                        route=route,
                    ),
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
