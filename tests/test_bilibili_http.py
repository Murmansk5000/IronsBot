import asyncio
from typing import Any, cast

import httpx

from ironsbot.integrations.http.bilibili import (
    ARTICLE_DETAIL_URL,
    DYNAMIC_DETAIL_URL,
    LIST_URL,
    OPUS_DETAIL_URL,
    fetch_bili_dynamic_detail,
    fetch_bili_feed,
)
from ironsbot.services.bilibili.content import DynamicContentCompactor
from ironsbot.services.bilibili.hydration import hydrate_dynamic_item
from ironsbot.services.bilibili.parser import (
    dynamic_body_hydration_reason,
    dynamic_content,
)
from ironsbot.services.bilibili.service import BiliFeedResponse

DETAIL_AND_OPUS_REQUEST_COUNT = 2
SUMMARY_MAX_CHARS = 500
CONTENT_MAX_CHARS = 800


def test_dynamic_requests_opt_in_to_opus_style() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": 0, "data": {}})

    async def fetch() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fetch_bili_feed(client, "test-cookie")
            await fetch_bili_dynamic_detail(client, "test-cookie", "123456")

    asyncio.run(fetch())

    assert str(requests[0].url).startswith(LIST_URL)
    assert str(requests[1].url).startswith(DYNAMIC_DETAIL_URL)
    assert requests[0].url.params["features"] == "itemOpusStyle"
    assert requests[1].url.params["features"] == "itemOpusStyle"


def _dynamic_item(major: dict[str, Any]) -> dict[str, Any]:
    return {
        "id_str": "123456",
        "modules": {
            "module_author": {"mid": 987654},
            "module_dynamic": {"major": major},
        },
    }


def test_truncated_opus_uses_full_paragraphs_before_hydration() -> None:
    requests: list[httpx.Request] = []
    source = _dynamic_item(
        {"opus": {"summary": {"text": "半截正文...", "has_more": True}}}
    )
    full_body = "完整的测试正文。" * 120

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url).startswith(DYNAMIC_DETAIL_URL):
            return httpx.Response(200, json={"code": 0, "data": {"item": source}})
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
                                                    {"word": {"words": full_body}}
                                                ]
                                            }
                                        },
                                        {"pic": {"pics": [{"url": "image.test"}]}},
                                    ]
                                }
                            }
                        ]
                    }
                },
            },
        )

    async def fetch() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await hydrate_dynamic_item(
                source,
                cookie="test-cookie",
                fetch_detail=lambda cookie, item_id: fetch_bili_dynamic_detail(
                    client, cookie, item_id
                ),
            )

    hydrated = asyncio.run(fetch())
    assert len(requests) == DETAIL_AND_OPUS_REQUEST_COUNT
    assert str(requests[1].url).startswith(OPUS_DETAIL_URL)
    assert dynamic_content(hydrated) == full_body
    assert dynamic_body_hydration_reason(hydrated) is None

    summarized_lengths: list[int] = []

    async def summarize(text: str, *, max_chars: int) -> str:
        summarized_lengths.append(len(text))
        assert max_chars == SUMMARY_MAX_CHARS
        return "完整正文的总结"

    compacted = asyncio.run(
        DynamicContentCompactor(
            summarizer=summarize,
            content_max_chars=CONTENT_MAX_CHARS,
            summary_max_chars=SUMMARY_MAX_CHARS,
            use_ai=True,
        ).compact(
            dynamic_content(hydrated)
        )
    )
    assert compacted is not None and compacted.generated_by_ai
    assert summarized_lengths == [len(full_body)]


def test_failed_opus_request_does_not_claim_summary_is_complete() -> None:
    source = _dynamic_item(
        {"opus": {"summary": {"text": "半截正文...", "has_more": True}}}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(DYNAMIC_DETAIL_URL):
            return httpx.Response(200, json={"code": 0, "data": {"item": source}})
        return httpx.Response(200, json={"code": -352})

    async def fetch() -> BiliFeedResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_bili_dynamic_detail(client, "test-cookie", "123456")

    response = asyncio.run(fetch())
    payload = cast("dict[str, Any]", response.data)
    assert dynamic_body_hydration_reason(payload["data"]["item"]) == "truncated"


def test_article_body_is_restored_from_article_endpoint() -> None:
    source = _dynamic_item({"article": {"id": 456789, "desc": "半截专栏正文"}})
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if str(request.url).startswith(DYNAMIC_DETAIL_URL):
            return httpx.Response(200, json={"code": 0, "data": {"item": source}})
        return httpx.Response(
            200,
            json={"code": 0, "data": {"content": "完整专栏正文" * 100}},
        )

    async def fetch() -> BiliFeedResponse:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await fetch_bili_dynamic_detail(client, "test-cookie", "123456")

    response = asyncio.run(fetch())
    assert str(requests[1].url).startswith(ARTICLE_DETAIL_URL)
    payload = cast("dict[str, Any]", response.data)
    assert dynamic_body_hydration_reason(payload["data"]["item"]) is None
