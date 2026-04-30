from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from intelligent_search_agent.agent.assistant.lexicon import (
    ASSET_KIND_ALIASES,
    DOCUMENT_TERMS,
    FOLLOWUP_TERMS,
    IMAGE_TERMS,
    tokens,
)


def message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(getattr(message, "role", "") or "")


def clean_message_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def recent_history_lines(messages: Sequence[Any] | None, limit: int = 6) -> list[str]:
    if not messages:
        return []

    lines: list[str] = []
    for message in messages[-limit:]:
        role = message_role(message)
        content = clean_message_text(message_content(message))
        if role in {"user", "assistant"} and content:
            lines.append(f"{role}: {content[:500]}")
    return lines


def last_user_question(messages: Sequence[Any] | None) -> str | None:
    if not messages:
        return None
    for message in reversed(messages):
        if message_role(message) == "user":
            content = clean_message_text(message_content(message))
            if content:
                return content
    return None


def looks_like_followup(question: str) -> bool:
    question_tokens = tokens(question)
    if not question_tokens:
        return False
    if question_tokens & FOLLOWUP_TERMS:
        return True

    all_asset_kind_terms = set().union(*ASSET_KIND_ALIASES.values())
    if len(question_tokens) <= 4 and question_tokens & (
        IMAGE_TERMS | DOCUMENT_TERMS | all_asset_kind_terms
    ):
        return True
    return bool(question_tokens & {"it", "that", "them", "those", "these"})


def contextual_question(question: str, messages: Sequence[Any] | None) -> str:
    previous = last_user_question(messages)
    if not previous or not looks_like_followup(question):
        return question
    return f"{previous}. Follow-up constraint: {question}"
