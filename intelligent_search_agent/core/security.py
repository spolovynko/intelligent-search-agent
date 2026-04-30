from __future__ import annotations

from urllib.parse import urlparse

from fastapi import Header, HTTPException, status

from intelligent_search_agent.core.config import get_settings


def source_url_allowed(url: str | None) -> bool:
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False

    settings = get_settings()
    allowed_hosts = {host.lower() for host in settings.allowed_source_url_hosts}
    if not allowed_hosts:
        return settings.environment.lower() in {"dev", "local"}

    host = (urlparse(url).hostname or "").lower()
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts)


def require_admin_api_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    settings = get_settings()
    if not settings.enable_admin_api:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Admin API is disabled")

    if settings.admin_api_key:
        if x_admin_key != settings.admin_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Valid X-Admin-Key header required",
            )
        return

    if settings.environment.lower() not in {"dev", "local"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ADMIN_API_KEY is required outside local/dev environments",
        )
