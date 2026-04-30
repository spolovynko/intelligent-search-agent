from __future__ import annotations

import json
from typing import Any


def sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
