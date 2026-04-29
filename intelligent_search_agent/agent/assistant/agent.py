import time

from pydantic_ai import Agent, RunContext

from intelligent_search_agent.agent.assistant.deps import AgentDeps
from intelligent_search_agent.agent.assistant.prompt import ASSISTANT_PROMPT
from intelligent_search_agent.core.config import get_settings
from intelligent_search_agent.db.telemetry import DBTimings


async def search_assets(
    ctx: RunContext[AgentDeps],
    search_query: str,
    asset_kind: str | None = None,
    language: str | None = None,
    file_type: str | None = None,
    year: int | None = None,
    campaign_context: str | None = None,
    period: str | None = None,
) -> str:
    """Search assets using hybrid semantic + keyword search with optional metadata filters."""
    db = ctx.deps.db
    total_start = time.perf_counter()
    results = await db.assets.search(
        search_query,
        asset_kind=asset_kind,
        language=language,
        file_type=file_type,
        year=year,
        campaign_context=campaign_context,
        period=period,
    )

    timings = db.telemetry.last_timings or DBTimings()
    timings.total_ms = (time.perf_counter() - total_start) * 1000
    db.telemetry.last_timings = timings

    if not results:
        return f"No assets matched '{search_query}'."

    lines = [
        f"Found {len(results)} asset results.",
        "",
        "| ID | Description | Project | Year | Kind | Language | Link |",
        "|----|-------------|---------|------|------|----------|------|",
    ]
    for item in results:
        description = (item.get("description") or item.get("file_name") or "").replace("|", "/")
        if len(description) > 120:
            description = description[:117] + "..."
        project = (item.get("project_name") or "").replace("|", "/")
        link = f"/v1/assets/{item['id']}/file"
        lines.append(
            f"| {item['id']} | {description} | {project} | {item.get('project_year') or ''} | "
            f"{item.get('asset_kind') or ''} | {item.get('language') or ''} | {link} |"
        )
    return "\n".join(lines)


async def search_documents(
    ctx: RunContext[AgentDeps],
    search_query: str,
    doc_type: str | None = None,
    language: str | None = None,
) -> str:
    """Search indexed document chunks using hybrid semantic + keyword search."""
    db = ctx.deps.db
    results = await db.documents.search(search_query, doc_type=doc_type, language=language)

    if not results:
        return f"No document chunks matched '{search_query}'."

    lines = [
        f"Found {len(results)} document results.",
        "",
        "| Document | Page | Heading | Excerpt |",
        "|----------|------|---------|---------|",
    ]
    for item in results:
        excerpt = (item.get("content") or "").replace("\n", " ").replace("|", "/")
        if len(excerpt) > 180:
            excerpt = excerpt[:177] + "..."
        lines.append(
            f"| {(item.get('document_title') or '').replace('|', '/')} | "
            f"{item.get('page_number') or ''} | {(item.get('heading') or '').replace('|', '/')} | "
            f"{excerpt} |"
        )
    return "\n".join(lines)


async def search_meetings(
    ctx: RunContext[AgentDeps],
    search_query: str | None = None,
    latest_only: bool = False,
    week: int | None = None,
    month: int | None = None,
    year: int | None = None,
    category: str | None = None,
    responsible: str | None = None,
    include_absences: bool = True,
    min_similarity: float | None = None,
) -> str:
    """Search meeting topics with semantic search and structured meeting filters."""
    settings = get_settings()
    db = ctx.deps.db
    limit = 500 if latest_only else settings.rag_top_k
    results = await db.meetings.search_topics(
        query=search_query,
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

    if not results:
        return "No matching meeting topics found."

    lines = [
        f"Found {len(results)} meeting topic results.",
        "",
        "| Meeting | Date | Week | Category | Topic | Responsible | Status | Content |",
        "|---------|------|------|----------|-------|-------------|--------|---------|",
    ]
    for item in results:
        content = (item.get("content") or "").replace("\n", " ").replace("|", "/")
        if len(content) > 160:
            content = content[:157] + "..."
        lines.append(
            f"| {(item.get('meeting_title') or '').replace('|', '/')} | {item.get('meeting_date') or ''} | "
            f"{item.get('week_number') or ''} | {(item.get('category') or '').replace('|', '/')} | "
            f"{(item.get('topic') or '').replace('|', '/')} | {(item.get('responsible') or '').replace('|', '/')} | "
            f"{(item.get('status') or '').replace('|', '/')} | {content} |"
        )
    return "\n".join(lines)


def build_agent() -> Agent[AgentDeps, str]:
    settings = get_settings()
    assistant = Agent(
        settings.pydantic_ai_model_string,
        deps_type=AgentDeps,
        system_prompt=ASSISTANT_PROMPT,
    )
    assistant.tool(search_assets)
    assistant.tool(search_documents)
    assistant.tool(search_meetings)
    return assistant
