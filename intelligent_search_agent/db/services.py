from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from functools import partial
from typing import Any

from intelligent_search_agent.db.embeddings import get_embedding, get_embedding_sync
from intelligent_search_agent.db.pool import get_pool_sync
from intelligent_search_agent.db.queries.assets import semantic_search_assets_sync
from intelligent_search_agent.db.queries.documents import search_document_chunks_sync
from intelligent_search_agent.db.queries.meetings import search_meeting_topics_sync
from intelligent_search_agent.db.telemetry import DBTimings


@dataclass
class DbTelemetry:
    last_timings: DBTimings | None = None


class QueryExecutor:
    def __init__(self, settings):
        self._settings = settings

    def _execute_sync(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        pool_instance = get_pool_sync(self._settings)
        conn = pool_instance.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if cur.description is None:
                    conn.commit()
                    return []
                return [dict(row) for row in cur.fetchall()]
        finally:
            pool_instance.putconn(conn)

    async def execute(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._execute_sync, sql, params))


class EmbeddingService:
    def __init__(self, settings):
        self._settings = settings

    async def get_embedding(self, text: str) -> list[float]:
        return await get_embedding(text, settings=self._settings)

    def get_embedding_sync(self, text: str) -> list[float]:
        return get_embedding_sync(text, settings=self._settings)


class AssetSearchService:
    def __init__(self, settings, telemetry: DbTelemetry):
        self._settings = settings
        self._telemetry = telemetry

    async def search(
        self,
        query: str,
        limit: int | None = None,
        asset_kind: str | None = None,
        language: str | None = None,
        file_type: str | None = None,
        year: int | None = None,
        campaign_context: str | None = None,
        period: str | None = None,
    ) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        results, timings = await loop.run_in_executor(
            None,
            partial(
                semantic_search_assets_sync,
                query,
                limit or self._settings.rag_top_k,
                self._settings.rag_candidate_k,
                self._settings.rag_min_similarity,
                self._settings.rag_hybrid_alpha,
                asset_kind,
                language,
                file_type,
                year,
                campaign_context,
                period,
                self._settings,
            ),
        )
        self._telemetry.last_timings = timings
        return results


class DocumentSearchService:
    def __init__(self, settings, telemetry: DbTelemetry):
        self._settings = settings
        self._telemetry = telemetry

    async def search(
        self,
        query: str,
        limit: int | None = None,
        doc_type: str | None = None,
        language: str | None = None,
    ) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        results, timings = await loop.run_in_executor(
            None,
            partial(
                search_document_chunks_sync,
                query,
                limit or self._settings.rag_top_k,
                self._settings.rag_candidate_k,
                self._settings.rag_min_similarity,
                self._settings.rag_hybrid_alpha,
                doc_type,
                language,
                self._settings,
            ),
        )
        self._telemetry.last_timings = timings
        return results


class MeetingSearchService:
    def __init__(self, settings, telemetry: DbTelemetry):
        self._settings = settings
        self._telemetry = telemetry

    async def search_topics(
        self,
        query: str | None,
        limit: int | None = None,
        min_similarity: float | None = None,
        year: int | None = None,
        week: int | None = None,
        month: int | None = None,
        category: str | None = None,
        responsible: str | None = None,
        include_absences: bool = True,
        latest_only: bool = False,
    ) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        results, timings = await loop.run_in_executor(
            None,
            partial(
                search_meeting_topics_sync,
                query,
                limit or self._settings.rag_top_k,
                min_similarity if min_similarity is not None else self._settings.rag_min_similarity,
                year,
                week,
                month,
                category,
                responsible,
                include_absences,
                latest_only,
                self._settings,
            ),
        )
        self._telemetry.last_timings = timings
        return results


class ChatSessionService:
    def __init__(self, settings):
        self._settings = settings

    def _ensure_session_sync(self, session_id: str, title: str | None, metadata: dict[str, Any]) -> None:
        pool_instance = get_pool_sync(self._settings)
        conn = pool_instance.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_sessions (id, title, metadata)
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (id) DO UPDATE SET
                        title = COALESCE(chat_sessions.title, EXCLUDED.title),
                        metadata = chat_sessions.metadata || EXCLUDED.metadata,
                        updated_at = NOW()
                    """,
                    (session_id, title, json.dumps(metadata)),
                )
            conn.commit()
        finally:
            pool_instance.putconn(conn)

    async def ensure_session(
        self,
        session_id: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(self._ensure_session_sync, session_id, title, metadata or {}),
        )

    def _append_message_sync(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        pool_instance = get_pool_sync(self._settings)
        conn = pool_instance.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO chat_messages (session_id, role, content, metadata)
                    VALUES (%s, %s, %s, %s::jsonb)
                    """,
                    (session_id, role, content, json.dumps(metadata)),
                )
                cur.execute(
                    "UPDATE chat_sessions SET updated_at = NOW() WHERE id = %s",
                    (session_id,),
                )
            conn.commit()
        finally:
            pool_instance.putconn(conn)

    async def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            partial(self._append_message_sync, session_id, role, content, metadata or {}),
        )

    def _recent_messages_sync(self, session_id: str, limit: int) -> list[dict[str, Any]]:
        pool_instance = get_pool_sync(self._settings)
        conn = pool_instance.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT role, content, metadata, created_at
                    FROM chat_messages
                    WHERE session_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (session_id, limit),
                )
                rows = [dict(row) for row in cur.fetchall()]
            rows.reverse()
            return rows
        finally:
            pool_instance.putconn(conn)

    async def recent_messages(self, session_id: str, limit: int = 10) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._recent_messages_sync, session_id, limit))

    def _list_sessions_sync(self, limit: int) -> list[dict[str, Any]]:
        pool_instance = get_pool_sync(self._settings)
        conn = pool_instance.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT s.id, s.title, s.metadata, s.created_at, s.updated_at, COUNT(m.id) AS message_count
                    FROM chat_sessions s
                    LEFT JOIN chat_messages m ON m.session_id = s.id
                    GROUP BY s.id
                    ORDER BY s.updated_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cur.fetchall()]
        finally:
            pool_instance.putconn(conn)

    async def list_sessions(self, limit: int = 25) -> list[dict[str, Any]]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(self._list_sessions_sync, limit))


def timings_snapshot(telemetry: DbTelemetry) -> DBTimings:
    return telemetry.last_timings or DBTimings()
