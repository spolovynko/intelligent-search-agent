from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_ai import Agent

from intelligent_search_agent.agent.assistant.conversation import (
    contextual_question,
    recent_history_lines,
)
from intelligent_search_agent.agent.assistant.lexicon import (
    ASSET_KIND_ALIASES,
    ASSET_KIND_VALUES,
    DOCUMENT_TERMS,
    HISTORY_TERMS,
    IMAGE_TERMS,
    MIXED_TERMS,
    QUESTION_TERMS,
    tokens,
)
from intelligent_search_agent.core.config import get_settings

logger = logging.getLogger(__name__)

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
        description="Short semantic search query to use for retrieval. Leave empty only for general chat.",
    )
    needs_assets: bool = False
    needs_documents: bool = False
    display_mode: Literal["chat", "asset_table", "mixed"] = "chat"
    asset_kind: (
        Literal[
            "photo",
            "painting",
            "illustration",
            "map",
            "document_scan",
            "poster",
            "architecture",
            "object",
            "other",
        ]
        | None
    ) = None
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


def normalize_route(route: AssistantRoute, question: str) -> AssistantRoute:
    if route.intent != AssistantIntent.GENERAL_CHAT and not route.search_query:
        route.search_query = question
    return route.model_validate(route.model_dump())


def apply_user_intent_overrides(route: AssistantRoute, question: str) -> AssistantRoute:
    question_tokens = tokens(question)
    explicit_assets = bool(question_tokens & IMAGE_TERMS)
    explicit_answer = bool(question_tokens & (DOCUMENT_TERMS | QUESTION_TERMS))
    history_question = bool(question_tokens & HISTORY_TERMS) and bool(
        question_tokens & (QUESTION_TERMS | DOCUMENT_TERMS)
    )

    if explicit_assets and explicit_answer:
        route.intent = AssistantIntent.MIXED_SEARCH
    elif explicit_assets:
        route.intent = AssistantIntent.IMAGE_SEARCH
    elif not explicit_assets and route.intent == AssistantIntent.IMAGE_SEARCH:
        route.intent = (
            AssistantIntent.DOCUMENT_ANSWER if history_question else AssistantIntent.GENERAL_CHAT
        )

    return normalize_route(route, question)


def heuristic_route(question: str) -> AssistantRoute:
    question_tokens = tokens(question)
    wants_assets = bool(question_tokens & IMAGE_TERMS)
    wants_documents = bool(question_tokens & (DOCUMENT_TERMS | HISTORY_TERMS | QUESTION_TERMS))
    wants_mixed = wants_assets and bool(question_tokens & (DOCUMENT_TERMS | MIXED_TERMS))

    if wants_mixed:
        intent = AssistantIntent.MIXED_SEARCH
    elif wants_assets:
        intent = AssistantIntent.IMAGE_SEARCH
    elif wants_documents:
        intent = AssistantIntent.DOCUMENT_ANSWER
    else:
        intent = AssistantIntent.GENERAL_CHAT

    asset_kind = next((item for item in sorted(ASSET_KIND_VALUES) if item in question_tokens), None)
    return apply_user_intent_overrides(
        AssistantRoute(
            intent=intent,
            search_query=question if intent != AssistantIntent.GENERAL_CHAT else "",
            needs_assets=intent in {AssistantIntent.IMAGE_SEARCH, AssistantIntent.MIXED_SEARCH},
            needs_documents=intent
            in {AssistantIntent.DOCUMENT_ANSWER, AssistantIntent.MIXED_SEARCH},
            asset_kind=asset_kind,
            confidence=0.45,
        ),
        question,
    )


def asset_kind_filter(question: str, route: AssistantRoute) -> str | None:
    if not route.asset_kind or route.asset_kind == "other":
        return None

    question_tokens = tokens(question)
    return (
        route.asset_kind
        if question_tokens & ASSET_KIND_ALIASES.get(route.asset_kind, set())
        else None
    )


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
        result = await router.run(prompt, model_settings={"temperature": 0.0})
        return apply_user_intent_overrides(result.output, effective_question)
    except Exception as exc:
        logger.warning("Structured request routing failed; using heuristic route: %s", exc)
        return fallback


def choose_sources(question: str) -> tuple[bool, bool]:
    route = heuristic_route(question)
    return route.needs_assets, route.needs_documents
