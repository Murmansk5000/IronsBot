from __future__ import annotations

import json
from dataclasses import asdict

import httpx
import pytest

from ironsbot.integrations.qq_official.api_errors import (
    QQOfficialApiError,
    QQOfficialHttpClient,
    qq_official_exception_result,
)
from ironsbot.integrations.qq_official.delivery_diagnostics import delivery_phase
from ironsbot.integrations.qq_official.safe_diagnostics import safe_platform_message
from ironsbot.integrations.storage.proactive_tasks import decode_result

MAX_EXPLANATION = 256
NOT_FOUND = 404


def test_platform_explanation_is_bounded_and_redacted() -> None:
    text = safe_platform_message(
        "missing upload_id=opaque-secret\nhttps://cos.test/private?sign=secret "
        "C48E6DA04773305806E3D1A3B665564E authorization: shortsecret " + "x" * 500
    )
    assert len(text) <= MAX_EXPLANATION
    for secret in ("opaque-secret", "cos.test", "shortsecret", "C48E6", "\n"):
        assert secret not in text
    assert safe_platform_message({"unexpected": "secret"}) == "平台未提供错误说明"


@pytest.mark.asyncio
async def test_platform_details_survive_phase_and_receipt_storage() -> None:
    async def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"code": 11001, "message": "upload task missing; token=secret"},
            headers={"x-tps-trace-id": "fictional-trace"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(RuntimeError) as caught:
            async with delivery_phase("upload_confirm"):
                await QQOfficialHttpClient(client).request(
                    "POST",
                    "https://api.test/v2/groups/private-group/upload_part_finish",
                )
    result = qq_official_exception_result(caught.value)
    restored = decode_result(json.dumps(asdict(result)))
    assert restored.failure_phase == "upload_confirm"
    assert restored.http_status == NOT_FOUND
    assert restored.request_method == "POST"
    assert restored.request_endpoint == "/v2/groups/{target}/upload_part_finish"
    assert restored.trace_id == "fictional-trace"
    assert "upload task missing" in (restored.error_message or "")
    assert "secret" not in (restored.error_message or "")
    assert result.failure_kind is restored.failure_kind


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not json", b"[]", b'{"message": null}'])
async def test_invalid_platform_explanation_never_exposes_response(body: bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(404, content=body))
    ) as client:
        with pytest.raises(QQOfficialApiError) as caught:
            await QQOfficialHttpClient(client).request(
                "POST", "https://api.test/private"
            )
    assert str(caught.value) == "平台未提供错误说明"
    assert caught.value.endpoint == "平台未提供接口模板"
