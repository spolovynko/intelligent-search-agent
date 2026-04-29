from dataclasses import dataclass


@dataclass
class DBTimings:
    embedding_ms: float = 0.0
    vector_search_ms: float = 0.0
    detail_fetch_ms: float = 0.0
    total_ms: float = 0.0

    @property
    def db_total_ms(self) -> float:
        return self.embedding_ms + self.vector_search_ms + self.detail_fetch_ms
