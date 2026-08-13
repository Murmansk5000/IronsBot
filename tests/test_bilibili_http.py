import asyncio

import httpx

from ironsbot.integrations.http.bilibili import (
    DYNAMIC_DETAIL_URL,
    LIST_URL,
    fetch_bili_dynamic_detail,
    fetch_bili_feed,
)


def test_dynamic_requests_opt_in_to_opus_style() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": {}})

    async def fetch() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            await fetch_bili_feed(client, "test-cookie")
            await fetch_bili_dynamic_detail(client, "test-cookie", "123456")

    asyncio.run(fetch())

    assert str(requests[0].url).startswith(LIST_URL)
    assert str(requests[1].url).startswith(DYNAMIC_DETAIL_URL)
    assert requests[0].url.params["features"] == "itemOpusStyle"
    assert requests[1].url.params["features"] == "itemOpusStyle"
