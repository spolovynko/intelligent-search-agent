from datetime import date
from typing import Any

from pydantic import BaseModel, Field


class TopicItem(BaseModel):
    id: int | None = None
    category: str | None = None
    topic: str | None = None
    content: str | None = None
    responsible: str | None = None
    status: str | None = None
    deadline: str | None = None
    is_absence: bool | None = None
    meeting_id: int | None = None
    meeting_title: str | None = None
    week_number: int | None = None
    year: int | None = None
    meeting_date: date | None = None
    similarity: float | None = None
    metadata: dict[str, Any] | None = None


class MeetingSummary(BaseModel):
    id: int
    title: str | None = None
    week_number: int | None = None
    year: int | None = None
    meeting_date: date | None = None
    participants: str | None = None
    topic_count: int | None = None


class MeetingDetail(BaseModel):
    id: int
    title: str | None = None
    week_number: int | None = None
    year: int | None = None
    meeting_date: date | None = None
    participants: str | None = None
    source_uri: str | None = None
    topics: list[TopicItem] = Field(default_factory=list)
    topics_by_category: dict[str, list[TopicItem]] = Field(default_factory=dict)


class MeetingListResponse(BaseModel):
    meetings: list[MeetingSummary]
    count: int


class TopicSearchResponse(BaseModel):
    query: str | None = None
    results: list[TopicItem]
    count: int
