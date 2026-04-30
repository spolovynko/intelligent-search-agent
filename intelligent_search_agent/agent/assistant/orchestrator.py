import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

from pydantic_ai.messages import ModelMessage
from pydantic_ai.usage import UsageLimits

from intelligent_search_agent.agent.assistant.agent import build_agent
from intelligent_search_agent.agent.assistant.deps import AgentDeps
from intelligent_search_agent.core.config import get_settings
from intelligent_search_agent.db import Database

logger = logging.getLogger(__name__)


async def ask_stream(
    question: str,
    message_history: list[ModelMessage] | None = None,
) -> AsyncGenerator[str, None]:
    settings = get_settings()
    total_start = time.perf_counter()
    padding = " " * 1024

    yield f"data: {json.dumps({'type': 'status', 'message': 'Thinking...'})}{padding}\n\n"
    await asyncio.sleep(0)

    try:
        db = Database()
        deps = AgentDeps(db=db, question=question)
        agent = build_agent()
        first_token_time: float | None = None
        input_tokens = 0
        output_tokens = 0

        async with agent.run_stream(
            question,
            deps=deps,
            usage_limits=UsageLimits(request_limit=settings.agent_request_limit),
            message_history=message_history,
        ) as stream:
            async for chunk in stream.stream_text(delta=True):
                if first_token_time is None:
                    first_token_time = time.perf_counter()
                    logger.info(
                        "Time to first token: %.1fms", (first_token_time - total_start) * 1000
                    )
                yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

            try:
                usage = stream.usage()
                input_tokens = usage.request_tokens or 0
                output_tokens = usage.response_tokens or 0
            except Exception as exc:
                logger.warning("Could not read usage: %s", exc)

        total_ms = (time.perf_counter() - total_start) * 1000
        db_timings = db.telemetry.last_timings
        db_total = db_timings.db_total_ms if db_timings else 0.0
        done_data = {
            "type": "done",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "input_cost_usd": round(input_tokens * settings.model_input_cost_per_token, 6),
                "output_cost_usd": round(output_tokens * settings.model_output_cost_per_token, 6),
                "model": settings.openai_model,
            },
            "performance": {
                "ttft_ms": round((first_token_time - total_start) * 1000, 1)
                if first_token_time
                else 0.0,
                "embedding_ms": round(db_timings.embedding_ms, 1) if db_timings else 0.0,
                "vector_search_ms": round(db_timings.vector_search_ms, 1) if db_timings else 0.0,
                "detail_fetch_ms": round(db_timings.detail_fetch_ms, 1) if db_timings else 0.0,
                "db_total_ms": round(db_total, 1),
                "llm_ms": round(max(total_ms - db_total, 0), 1),
                "total_ms": round(total_ms, 1),
            },
        }
        yield f"data: {json.dumps(done_data)}\n\n"
    except Exception as exc:
        logger.exception("Chat stream failed")
        yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"
