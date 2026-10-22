from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from starlette.requests import Request

if TYPE_CHECKING:
    from collections.abc import Mapping

    from starlette.types import Message


def http_request(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    content: str | bytes | None,
) -> Request:
    target = urlsplit(url)
    body = content.encode("utf-8") if isinstance(content, str) else content or b""

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(
        {
            "type": "http",
            "method": method,
            "path": target.path,
            "scheme": target.scheme,
            "query_string": target.query.encode("utf-8"),
            "headers": [
                (key.lower().encode("utf-8"), value.encode("utf-8"))
                for key, value in headers.items()
            ],
        },
        receive=receive,
    )
