# SPDX-License-Identifier: MIT
import asyncio
from typing import Any

import httpx

from ironsbot.integrations.http.clients import HttpClients
from ironsbot.integrations.http.seer_images import HttpSeerImageSource


class _ConcurrentDetectingClient(httpx.AsyncClient):
    def __init__(self) -> None:
        super().__init__()
        self.in_flight = 0
        self.max_in_flight = 0

    async def get(self, url: str, *args: Any, **kwargs: Any) -> httpx.Response:
        _ = (args, kwargs)
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return httpx.Response(
            200,
            content=b"image",
            request=httpx.Request("GET", url),
        )


async def _fetch_many_images() -> int:
    cache = _ConcurrentDetectingClient()
    clients = HttpClients(cache=cache)
    images = HttpSeerImageSource(clients)
    try:
        await asyncio.gather(
            *(
                images.fetch("pet_body", str(i), fallback=False)
                for i in range(8)
            )
        )
        return cache.max_in_flight
    finally:
        await clients.close()


def test_image_fetches_are_serialized_for_shared_cache_client() -> None:
    assert asyncio.run(_fetch_many_images()) == 1
