import httpx

from ironsbot.services.ai.responses import parse_ai_response


def test_parse_ai_response_extracts_reply() -> None:
    result = parse_ai_response(
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": " OK "}}]},
        )
    )

    assert result.ok
    assert result.reply == "OK"


def test_parse_ai_response_extracts_http_error_detail() -> None:
    result = parse_ai_response(
        httpx.Response(
            429,
            json={"error": {"message": "rate limited"}},
        )
    )

    assert not result.ok
    assert result.error_kind == "http"
    assert result.error_title == "请求过于频繁或触发限流"
    assert result.error_detail == "rate limited"


def test_parse_ai_response_rejects_invalid_json() -> None:
    result = parse_ai_response(
        httpx.Response(
            200,
            text="not-json",
            headers={"content-type": "text/plain"},
        )
    )

    assert not result.ok
    assert result.error_kind == "invalid_json"
    assert result.error_detail == "not-json"


def test_parse_ai_response_rejects_missing_content() -> None:
    result = parse_ai_response(httpx.Response(200, json={"choices": []}))

    assert not result.ok
    assert result.error_kind == "empty_reply"
    assert "choices[0].message.content" in result.error_detail
