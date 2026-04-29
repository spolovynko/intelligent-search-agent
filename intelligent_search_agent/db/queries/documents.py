import logging
import re
import time
from typing import Any

from intelligent_search_agent.db.embeddings import get_embedding_sync, vector_to_pg
from intelligent_search_agent.db.pool import get_pool_sync
from intelligent_search_agent.db.telemetry import DBTimings

logger = logging.getLogger(__name__)

_STRIP_RE = re.compile(r"[^\w\s-]", re.UNICODE)


def _normalize_query(raw: str) -> str:
    return re.sub(r"\s+", " ", _STRIP_RE.sub(" ", raw)).strip()


def search_document_chunks_sync(
    query: str,
    limit: int,
    candidate_limit: int,
    min_similarity: float,
    hybrid_alpha: float,
    doc_type: str | None = None,
    language: str | None = None,
    settings=None,
) -> tuple[list[dict[str, Any]], DBTimings]:
    timings = DBTimings()
    total_start = time.perf_counter()

    embed_start = time.perf_counter()
    query_vector = vector_to_pg(get_embedding_sync(query, settings=settings))
    timings.embedding_ms = (time.perf_counter() - embed_start) * 1000

    conditions = ["c.embedding IS NOT NULL"]
    params: list[Any] = []
    if doc_type:
        conditions.append("d.doc_type = %s")
        params.append(doc_type)
    if language:
        conditions.append("d.language ILIKE %s")
        params.append(language)

    if len(conditions) > 1:
        min_similarity = min(min_similarity, 0.20)

    pool_instance = get_pool_sync(settings=settings)
    conn = pool_instance.getconn()
    try:
        with conn.cursor() as cur:
            vector_start = time.perf_counter()
            cur.execute(
                f"""
                WITH candidates AS (
                    SELECT
                        c.id,
                        1 - (c.embedding <=> %s::vector) AS vec_score,
                        COALESCE(
                            ts_rank_cd(
                                COALESCE(c.search_vector, to_tsvector('simple', COALESCE(c.content, ''))),
                                plainto_tsquery('simple', %s),
                                32
                            ),
                            0
                        ) AS kw_raw
                    FROM document_chunks c
                    JOIN documents d ON c.document_id = d.id
                    WHERE {" AND ".join(conditions)}
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                ),
                score_bounds AS (
                    SELECT MAX(kw_raw) AS max_kw FROM candidates
                )
                SELECT
                    c.id,
                    c.vec_score,
                    CASE WHEN b.max_kw > 0 THEN c.kw_raw / b.max_kw ELSE 0 END AS kw_score
                FROM candidates c, score_bounds b
                WHERE c.vec_score >= %s
                ORDER BY (
                    %s * c.vec_score +
                    %s * CASE WHEN b.max_kw > 0 THEN c.kw_raw / b.max_kw ELSE 0 END
                ) DESC
                LIMIT %s
                """,
                (
                    query_vector,
                    _normalize_query(query),
                    *params,
                    query_vector,
                    candidate_limit,
                    min_similarity,
                    hybrid_alpha,
                    1 - hybrid_alpha,
                    limit,
                ),
            )
            matches = cur.fetchall()
            timings.vector_search_ms = (time.perf_counter() - vector_start) * 1000

            if not matches:
                timings.total_ms = (time.perf_counter() - total_start) * 1000
                return [], timings

            chunk_ids = [row["id"] for row in matches]
            scores = {
                row["id"]: {
                    "vec_score": float(row["vec_score"] or 0),
                    "kw_score": float(row["kw_score"] or 0),
                    "similarity": (
                        hybrid_alpha * float(row["vec_score"] or 0)
                        + (1 - hybrid_alpha) * float(row["kw_score"] or 0)
                    ),
                }
                for row in matches
            }

            fetch_start = time.perf_counter()
            cur.execute(
                """
                SELECT
                    c.id,
                    c.document_id,
                    c.chunk_index,
                    c.heading,
                    c.content,
                    c.page_number,
                    c.metadata,
                    d.title AS document_title,
                    d.source_uri,
                    d.doc_type,
                    d.language
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE c.id = ANY(%s)
                """,
                (chunk_ids,),
            )
            results = [dict(row) for row in cur.fetchall()]
            timings.detail_fetch_ms = (time.perf_counter() - fetch_start) * 1000

            for row in results:
                row.update(scores[row["id"]])
            results.sort(key=lambda item: item["similarity"], reverse=True)
            timings.total_ms = (time.perf_counter() - total_start) * 1000
            logger.info("Document search completed in %.1fms", timings.total_ms)
            return results, timings
    finally:
        pool_instance.putconn(conn)
