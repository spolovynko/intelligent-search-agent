from typing import Any

from intelligent_search_agent.core.config import get_settings
from intelligent_search_agent.db.embeddings import close_http_client
from intelligent_search_agent.db.pool import close_pool as close_db_pool
from intelligent_search_agent.db.services import (
    AssetSearchService,
    ChatSessionService,
    DbTelemetry,
    DocumentSearchService,
    EmbeddingService,
    MeetingSearchService,
    QueryExecutor,
)


class Database:
    def __init__(self):
        self._settings = get_settings()
        self.telemetry = DbTelemetry()
        self.executor = QueryExecutor(self._settings)
        self.embeddings = EmbeddingService(self._settings)
        self.assets = AssetSearchService(self._settings, self.telemetry)
        self.documents = DocumentSearchService(self._settings, self.telemetry)
        self.meetings = MeetingSearchService(self._settings, self.telemetry)
        self.chat = ChatSessionService(self._settings)

    async def execute(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        return await self.executor.execute(sql, params)

    @property
    def last_timings(self):
        return self.telemetry.last_timings

    @classmethod
    async def close_pool(cls) -> None:
        close_db_pool()
        await close_http_client()
