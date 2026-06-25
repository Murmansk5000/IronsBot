# SPDX-License-Identifier: MIT
import asyncio

import nonebot

nonebot.init()

from ironsbot.utils.image import GetImage


class _FakeImageResponse:
    content = b"image"

    def raise_for_status(self) -> None:
        return None


class _ConcurrentDetectingClient:
    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0

    async def get(self, _url: str) -> _FakeImageResponse:
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0)
        self.in_flight -= 1
        return _FakeImageResponse()


async def _fetch_many_images() -> int:
    client = _ConcurrentDetectingClient()
    getter = GetImage("https://example.invalid/{}.png", client_getter=lambda: client)

    await asyncio.gather(*(getter.get_bytes(str(i)) for i in range(8)))
    return client.max_in_flight


def test_image_fetches_are_serialized_for_shared_cache_client() -> None:
    assert asyncio.run(_fetch_many_images()) == 1
