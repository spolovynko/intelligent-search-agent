import time
from typing import Any

from intelligent_search_agent.db.embeddings import get_embedding_sync, vector_to_pg
from intelligent_search_agent.db.pool import get_pool_sync
from intelligent_search_agent.db.telemetry import DBTimings


def search_meeting_topics_sync(
    query: str | None,
    limit: int,
    min_similarity: float,
    year: int | None = None,
    week: int | None = None,
    month: int | None = None,
    category: str | None = None,
    responsible: str | None = None,
    include_absences: bool = True,
    latest_only: bool = False,
    settings=None,
) -> tuple[list[dict[str, Any]], DBTimings]:
    timings = DBTimings()
    total_start = time.perf_counter()

    meeting_conditions: list[str] = []
    meeting_params: list[Any] = []
    topic_conditions: list[str] = []
    topic_params: list[Any] = []

    if year is not None:
        meeting_conditions.append("m.year = %s")
        meeting_params.append(year)
    if week is not None:
        meeting_conditions.append("m.week_number = %s")
        meeting_params.append(week)
    if month is not None:
        meeting_conditions.append("EXTRACT(MONTH FROM m.meeting_date) = %s")
        meeting_params.append(month)
    if not include_absences:
        topic_conditions.append("t.is_absence = FALSE")
    if category:
        topic_conditions.append("t.category = %s")
        topic_params.append(category)
    if responsible:
        topic_conditions.append("t.responsible ILIKE %s")
        topic_params.append(f"%{responsible}%")

    where_meeting = " AND ".join(meeting_conditions) if meeting_conditions else "TRUE"
    where_topic = " AND ".join(topic_conditions) if topic_conditions else "TRUE"

    pool_instance = get_pool_sync(settings=settings)
    conn = pool_instance.getconn()
    try:
        with conn.cursor() as cur:
            if latest_only:
                vector_start = time.perf_counter()
                cur.execute(
                    f"""
                    WITH latest AS (
                        SELECT id FROM status_meetings m
                        WHERE {where_meeting}
                        ORDER BY year DESC, week_number DESC, meeting_date DESC NULLS LAST
                        LIMIT 1
                    )
                    SELECT
                        t.id,
                        t.category,
                        t.topic,
                        t.content,
                        t.responsible,
                        t.status,
                        t.deadline,
                        t.is_absence,
                        m.id AS meeting_id,
                        m.title AS meeting_title,
                        m.week_number,
                        m.year,
                        m.meeting_date,
                        1.0 AS similarity
                    FROM topics t
                    JOIN status_meetings m ON t.meeting_id = m.id
                    JOIN latest l ON m.id = l.id
                    WHERE {where_topic}
                    ORDER BY t.category, t.topic
                    LIMIT %s
                    """,
                    (*meeting_params, *topic_params, limit),
                )
                results = [dict(row) for row in cur.fetchall()]
                timings.vector_search_ms = (time.perf_counter() - vector_start) * 1000
                timings.total_ms = (time.perf_counter() - total_start) * 1000
                return results, timings

            if not query:
                vector_start = time.perf_counter()
                cur.execute(
                    f"""
                    SELECT
                        t.id,
                        t.category,
                        t.topic,
                        t.content,
                        t.responsible,
                        t.status,
                        t.deadline,
                        t.is_absence,
                        m.id AS meeting_id,
                        m.title AS meeting_title,
                        m.week_number,
                        m.year,
                        m.meeting_date,
                        1.0 AS similarity
                    FROM topics t
                    JOIN status_meetings m ON t.meeting_id = m.id
                    WHERE {where_meeting} AND {where_topic}
                    ORDER BY m.year DESC, m.week_number DESC, t.category, t.topic
                    LIMIT %s
                    """,
                    (*meeting_params, *topic_params, limit),
                )
                results = [dict(row) for row in cur.fetchall()]
                timings.vector_search_ms = (time.perf_counter() - vector_start) * 1000
                timings.total_ms = (time.perf_counter() - total_start) * 1000
                return results, timings

            embed_start = time.perf_counter()
            query_vector = vector_to_pg(get_embedding_sync(query, settings=settings))
            timings.embedding_ms = (time.perf_counter() - embed_start) * 1000

            vector_start = time.perf_counter()
            cur.execute(
                f"""
                SELECT
                    t.id,
                    t.category,
                    t.topic,
                    t.content,
                    t.responsible,
                    t.status,
                    t.deadline,
                    t.is_absence,
                    m.id AS meeting_id,
                    m.title AS meeting_title,
                    m.week_number,
                    m.year,
                    m.meeting_date,
                    1 - (t.embedding <=> %s::vector) AS similarity
                FROM topics t
                JOIN status_meetings m ON t.meeting_id = m.id
                WHERE t.embedding IS NOT NULL
                  AND 1 - (t.embedding <=> %s::vector) >= %s
                  AND {where_meeting}
                  AND {where_topic}
                ORDER BY t.embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    query_vector,
                    query_vector,
                    min_similarity,
                    *meeting_params,
                    *topic_params,
                    query_vector,
                    limit,
                ),
            )
            results = [dict(row) for row in cur.fetchall()]
            timings.vector_search_ms = (time.perf_counter() - vector_start) * 1000
            timings.total_ms = (time.perf_counter() - total_start) * 1000
            return results, timings
    finally:
        pool_instance.putconn(conn)
