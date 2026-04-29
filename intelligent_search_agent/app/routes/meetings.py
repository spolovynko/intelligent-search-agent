from fastapi import APIRouter, HTTPException, Query

from intelligent_search_agent.db import Database
from intelligent_search_agent.models import MeetingDetail, MeetingListResponse, TopicSearchResponse

router = APIRouter(prefix="/v1/meetings", tags=["meetings"])


@router.get("", response_model=MeetingListResponse)
async def list_meetings(year: int | None = None, limit: int = Query(default=50, ge=1, le=100)):
    db = Database()
    if year is not None:
        rows = await db.execute(
            """
            SELECT
                m.id,
                m.title,
                m.week_number,
                m.year,
                m.meeting_date,
                m.participants,
                COUNT(t.id) AS topic_count
            FROM status_meetings m
            LEFT JOIN topics t ON m.id = t.meeting_id
            WHERE m.year = %s
            GROUP BY m.id
            ORDER BY m.year DESC, m.week_number DESC
            LIMIT %s
            """,
            (year, limit),
        )
    else:
        rows = await db.execute(
            """
            SELECT
                m.id,
                m.title,
                m.week_number,
                m.year,
                m.meeting_date,
                m.participants,
                COUNT(t.id) AS topic_count
            FROM status_meetings m
            LEFT JOIN topics t ON m.id = t.meeting_id
            GROUP BY m.id
            ORDER BY m.year DESC, m.week_number DESC
            LIMIT %s
            """,
            (limit,),
        )
    return {"meetings": rows, "count": len(rows)}


@router.get("/topics/search", response_model=TopicSearchResponse)
async def search_topics(
    q: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    year: int | None = None,
    week: int | None = None,
    month: int | None = None,
    category: str | None = None,
    responsible: str | None = None,
    include_absences: bool = True,
    latest_only: bool = False,
    min_similarity: float | None = Query(default=None, ge=0.0, le=1.0),
):
    db = Database()
    rows = await db.meetings.search_topics(
        query=q,
        limit=limit,
        min_similarity=min_similarity,
        year=year,
        week=week,
        month=month,
        category=category,
        responsible=responsible,
        include_absences=include_absences,
        latest_only=latest_only,
    )
    return {"query": q, "results": rows, "count": len(rows)}


@router.get("/{meeting_id}", response_model=MeetingDetail)
async def get_meeting(meeting_id: int):
    db = Database()
    meetings = await db.execute(
        """
        SELECT id, title, week_number, year, meeting_date, participants, source_uri
        FROM status_meetings
        WHERE id = %s
        """,
        (meeting_id,),
    )
    if not meetings:
        raise HTTPException(status_code=404, detail=f"Meeting {meeting_id} not found")

    topics = await db.execute(
        """
        SELECT id, category, topic, content, responsible, status, deadline, is_absence, metadata
        FROM topics
        WHERE meeting_id = %s
        ORDER BY category, id
        """,
        (meeting_id,),
    )
    grouped: dict[str, list[dict]] = {}
    for topic in topics:
        grouped.setdefault(topic.get("category") or "Uncategorized", []).append(topic)

    return {**meetings[0], "topics": topics, "topics_by_category": grouped}
