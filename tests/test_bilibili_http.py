import asyncio

import httpx

from ironsbot.integrations.http.bilibili import (
    DYNAMIC_DETAIL_URL,
    LIST_URL,
    OPUS_DETAIL_URL,
    fetch_bili_dynamic_detail,
    fetch_bili_feed,
)
from ironsbot.services.bilibili.service import BiliFeedResponse

DETAIL_AND_OPUS_REQUEST_COUNT = 2


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


def test_truncated_dynamic_detail_is_completed_from_opus_paragraphs() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url).startswith(DYNAMIC_DETAIL_URL):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "item": {
                            "id_str": "123456",
                            "modules": {
                                "module_dynamic": {
                                    "major": {
                                        "opus": {
                                            "summary": {
                                                "text": "半截正文",
                                                "has_more": True,
                                            },
                                            "pics": [{"url": "cover.png"}],
                                        }
                                    }
                                }
                            },
                        }
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "item": {
                        "modules": [
                            {
                                "module_content": {
                                    "paragraphs": [
                                        {
                                            "text": {
                                                "nodes": [
                                                    {"word": {"words": "第一段"}},
                                                    {"word": {"words": "正文"}},
                                                ]
                                            }
                                        },
                                        {"pic": {"pics": [{"url": "inside.png"}]}},
                                        {
                                            "text": {
                                                "nodes": [
                                                    {"word": {"words": "第二段"}}
                                                ]
                                            }
                                        },
                                    ]
                                }
                            }
                        ]
                    }
                },
            },
        )

    async def fetch() -> BiliFeedResponse:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await fetch_bili_dynamic_detail(
                client,
                "test-cookie",
                "123456",
            )

    response = asyncio.run(fetch())
    item = response.data["data"]["item"]  # type: ignore[index]
    summary = item["modules"]["module_dynamic"]["major"]["opus"]["summary"]

    assert len(requests) == DETAIL_AND_OPUS_REQUEST_COUNT
    assert str(requests[1].url).startswith(OPUS_DETAIL_URL)
    assert requests[1].url.params["id"] == "123456"
    assert summary == {"text": "第一段正文\n第二段", "has_more": False}
    assert item["modules"]["module_dynamic"]["major"]["opus"]["pics"] == [
        {"url": "cover.png"}
    ]


def test_failed_opus_completion_keeps_truncated_dynamic_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(DYNAMIC_DETAIL_URL):
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "item": {
                            "modules": {
                                "module_dynamic": {
                                    "major": {
                                        "opus": {
                                            "summary": {
                                                "text": "半截正文",
                                                "has_more": True,
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    },
                },
            )
        return httpx.Response(200, json={"code": -352})

    async def fetch() -> BiliFeedResponse:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as client:
            return await fetch_bili_dynamic_detail(client, "", "123456")

    response = asyncio.run(fetch())
    item = response.data["data"]["item"]  # type: ignore[index]
    summary = item["modules"]["module_dynamic"]["major"]["opus"]["summary"]
    assert summary == {"text": "半截正文", "has_more": True}
