import json
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, TextPart, UserPromptPart

from intelligent_search_agent.agent.assistant.companion import companion_stream
from intelligent_search_agent.agent import ask_stream
from intelligent_search_agent.models import ChatMessage, ChatRequest

router = APIRouter(prefix="/v1/chat", tags=["chat"])


def convert_history(messages: list[ChatMessage]) -> list[ModelMessage]:
    history: list[ModelMessage] = []
    for message in messages:
        if message.role == "user":
            history.append(ModelRequest(parts=[UserPromptPart(content=message.content)]))
        elif message.role == "assistant":
            history.append(ModelResponse(parts=[TextPart(content=message.content)]))
    return history


@router.post("/stream")
async def chat_stream(body: ChatRequest):
    request_id = uuid4().hex[:8]
    history = convert_history(body.messages) if body.messages else None

    async def stream_with_id():
        yield f"data: {json.dumps({'type': 'request', 'request_id': request_id})}\n\n"
        async for event in ask_stream(body.question, message_history=history):
            yield event

    return StreamingResponse(
        stream_with_id(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/companion/stream")
async def companion_chat_stream(body: ChatRequest):
    async def stream():
        async for event in companion_stream(
            body.question,
            messages=body.messages,
            session_id=body.session_id,
        ):
            yield event

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("")
async def chat(body: ChatRequest):
    chunks: list[str] = []
    done: dict | None = None
    error: str | None = None
    history = convert_history(body.messages) if body.messages else None

    async for event in ask_stream(body.question, message_history=history):
        if not event.startswith("data: "):
            continue
        data = json.loads(event[6:].strip())
        if data.get("type") == "chunk":
            chunks.append(data.get("content", ""))
        elif data.get("type") == "done":
            done = data
        elif data.get("type") == "error":
            error = data.get("message")

    return {
        "answer": "".join(chunks),
        "done": done,
        "error": error,
    }
