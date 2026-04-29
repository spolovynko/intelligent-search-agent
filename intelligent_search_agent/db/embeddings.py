import asyncio

import httpx

from intelligent_search_agent.core.config import get_settings

_http_client: httpx.AsyncClient | None = None
_http_client_lock = asyncio.Lock()


async def get_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        async with _http_client_lock:
            if _http_client is None:
                _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


def vector_to_pg(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.10g}" for value in vector) + "]"


async def get_embedding(text: str, settings=None) -> list[float]:
    settings = settings or get_settings()
    client = await get_http_client()
    url, headers, params, model_name = _build_embedding_request(settings)
    response = await client.post(
        url,
        headers=headers,
        params=params,
        json={"input": text, "model": model_name},
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def get_embedding_sync(text: str, settings=None) -> list[float]:
    settings = settings or get_settings()
    url, headers, params, model_name = _build_embedding_request(settings)
    response = httpx.post(
        url,
        headers=headers,
        params=params,
        json={"input": text, "model": model_name},
        timeout=30.0,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


async def close_http_client() -> None:
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None


def _build_embedding_request(settings) -> tuple[str, dict[str, str], dict[str, str] | None, str]:
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for embeddings.")

    base_url = (settings.openai_base_url or "https://api.openai.com/v1").rstrip("/")
    return (
        f"{base_url}/embeddings",
        {"Authorization": f"Bearer {settings.openai_api_key}"},
        None,
        settings.embedding_model,
    )
