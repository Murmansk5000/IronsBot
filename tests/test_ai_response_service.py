from ironsbot.services.ai.responses import parse_ai_response
from ironsbot.services.ai.service import _truncate_bilibili_summary


def test_parse_ai_response_extracts_reply() -> None:
    result = parse_ai_response(
        200,
        {"choices": [{"message": {"content": " OK "}}]},
    )

    assert result.ok
    assert result.reply == "OK"


def test_parse_ai_response_extracts_http_error_detail() -> None:
    result = parse_ai_response(
        429,
        {"error": {"message": "rate limited"}},
    )

    assert not result.ok
    assert result.error_kind == "http"
    assert result.error_title == "请求过于频繁或触发限流"
    assert result.error_detail == "rate limited"


def test_parse_ai_response_rejects_invalid_json() -> None:
    result = parse_ai_response(
        200,
        None,
        raw_text="not-json",
        valid_json=False,
    )

    assert not result.ok
    assert result.error_kind == "invalid_json"
    assert result.error_detail == "not-json"


def test_parse_ai_response_rejects_missing_content() -> None:
    result = parse_ai_response(200, {"choices": []})

    assert not result.ok
    assert result.error_kind == "empty_reply"
    assert "choices[0].message.content" in result.error_detail


def test_bilibili_summary_fallback_does_not_cut_a_numbered_item_midway() -> None:
    summary = _truncate_bilibili_summary(
        "一、联动开启。二、活动奖励丰富。三、这是没有结束的长条目内容",
        18,
    )

    assert summary == "一、联动开启。二、活动奖励丰富。"
