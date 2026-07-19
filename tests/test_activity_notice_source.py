import asyncio
from datetime import datetime, timezone

import httpx

from ironsbot.integrations.http.activity_notice import UnityNoticeSource


def test_unity_notice_source_normalizes_and_caches_response() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            content=b"line 1\\nline 2 &amp; more",
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond)
        ) as client:
            source = UnityNoticeSource(client, timeout_seconds=8)
            now = datetime(2026, 6, 1, tzinfo=timezone.utc)

            assert await source.fetch(now) == "line 1\nline 2 & more"
            assert await source.fetch(now) == "line 1\nline 2 & more"

    asyncio.run(run())

    assert len(requests) == 1
