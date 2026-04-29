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


def semantic_search_assets_sync(
    query: str,
    limit: int,
    candidate_limit: int,
    min_similarity: float,
    hybrid_alpha: float,
    asset_kind: str | None = None,
    language: str | None = None,
    file_type: str | None = None,
    year: int | None = None,
    campaign_context: str | None = None,
    period: str | None = None,
    settings=None,
) -> tuple[list[dict[str, Any]], DBTimings]:
    timings = DBTimings()
    total_start = time.perf_counter()

    embed_start = time.perf_counter()
    query_vector = vector_to_pg(get_embedding_sync(query, settings=settings))
    timings.embedding_ms = (time.perf_counter() - embed_start) * 1000

    conditions = ["a.embedding IS NOT NULL"]
    params: list[Any] = []

    if asset_kind:
        conditions.append("a.asset_kind = %s")
        params.append(asset_kind)
    if language:
        conditions.append("a.language ILIKE %s")
        params.append(language)
    if file_type:
        normalized_type = file_type if file_type.startswith(".") else f".{file_type}"
        conditions.append("a.file_type = %s")
        params.append(normalized_type.lower())
    if year is not None:
        conditions.append("p.year = %s")
        params.append(year)
    if campaign_context:
        conditions.append("a.campaign_context ILIKE %s")
        params.append(f"%{campaign_context}%")
    if period:
        conditions.append("a.period ILIKE %s")
        params.append(f"%{period}%")

    if len(conditions) > 1:
        min_similarity = min(min_similarity, 0.20)

    where_clause = " AND ".join(conditions)
    kw_query = _normalize_query(query)

    pool_instance = get_pool_sync(settings=settings)
    conn = pool_instance.getconn()
    try:
        with conn.cursor() as cur:
            vector_start = time.perf_counter()
            cur.execute(
                f"""
                WITH candidates AS (
                    SELECT
                        a.id,
                        1 - (a.embedding <=> %s::vector) AS vec_score,
                        COALESCE(
                            ts_rank_cd(
                                COALESCE(a.search_vector, to_tsvector('simple', COALESCE(a.embedding_text, ''))),
                                plainto_tsquery('simple', %s),
                                32
                            ),
                            0
                        ) AS kw_raw
                    FROM assets a
                    LEFT JOIN projects p ON a.project_id = p.id
                    WHERE {where_clause}
                    ORDER BY a.embedding <=> %s::vector
                    LIMIT %s
                ),
                score_bounds AS (
                    SELECT MAX(kw_raw) AS max_kw FROM candidates
                )
                SELECT
                    c.id,
                    c.vec_score,
                    c.kw_raw,
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
                    kw_query,
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

            asset_ids = [row["id"] for row in matches]
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
                    a.id,
                    a.external_id,
                    a.file_name,
                    a.file_path,
                    a.file_type,
                    a.file_size,
                    a.storage_backend,
                    a.storage_uri,
                    a.source_url,
                    a.thumbnail_uri,
                    a.asset_kind,
                    a.language,
                    a.period,
                    a.campaign_context,
                    a.description,
                    a.asset_content,
                    a.document_content,
                    a.image_width,
                    a.image_height,
                    a.metadata,
                    p.external_id AS project_external_id,
                    p.name AS project_name,
                    p.year AS project_year
                FROM assets a
                LEFT JOIN projects p ON a.project_id = p.id
                WHERE a.id = ANY(%s)
                """,
                (asset_ids,),
            )
            results = [dict(row) for row in cur.fetchall()]
            timings.detail_fetch_ms = (time.perf_counter() - fetch_start) * 1000

            for row in results:
                row.update(scores[row["id"]])
            results.sort(key=lambda item: item["similarity"], reverse=True)

            timings.total_ms = (time.perf_counter() - total_start) * 1000
            logger.info("Asset search completed in %.1fms", timings.total_ms)
            return results, timings
    finally:
        pool_instance.putconn(conn)
