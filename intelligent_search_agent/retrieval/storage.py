from pathlib import Path
from urllib.parse import quote

from intelligent_search_agent.core.config import get_settings


def resolve_asset_path(file_path: str | None, storage_uri: str | None = None) -> Path | None:
    settings = get_settings()
    raw = storage_uri or file_path
    if not raw:
        return None

    if raw.startswith(("http://", "https://", "s3://", "az://")):
        return None

    path = Path(raw)
    if not path.is_absolute():
        path = settings.asset_root / path
    return path


def file_url_from_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return None
    normalized = raw_path.strip()
    if normalized.lower().startswith("file://"):
        return normalized
    normalized = normalized.replace("/", "\\")
    if normalized.startswith("\\\\"):
        unc = normalized.lstrip("\\")
        parts = unc.split("\\")
        if len(parts) < 2:
            return None
        server = parts[0]
        share_path = "/".join(parts[1:]).replace("\\", "/")
        return f"file://{server}/{quote(share_path, safe='/')}"
    if len(normalized) >= 2 and normalized[1] == ":":
        drive = normalized[0].upper()
        rest = normalized[2:].lstrip("\\/").replace("\\", "/")
        return f"file:///{drive}:/{quote(rest, safe='/')}"
    return None
