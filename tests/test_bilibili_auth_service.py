from typing import cast

import httpx
import pytest

from ironsbot.services.bilibili.auth import (
    BiliLoginRuntimeState,
    LoginQrRequest,
    build_bili_login_cookie_incomplete_text,
    build_bili_login_notice_text,
    build_bili_login_poll_error_text,
    build_bili_login_qrcode_message_parts,
    build_bili_login_qrcode_request_failed_text,
    build_bili_login_qrcode_tip,
    build_bili_login_reason_detail,
    build_bili_login_success_text,
    classify_bili_login_poll_code,
    clear_bili_login_qr_if_matches,
    extract_bili_login_cookie,
    has_complete_bili_login_cookie,
    is_bili_auth_invalid,
    is_bili_login_qr_reusable,
    mark_bili_login_notice_sent,
    mark_bili_login_required,
    parse_bili_login_qrcode_response,
    reset_bili_login_notice_cooldown,
    should_send_bili_login_notice,
    store_bili_login_qr_request,
)


def test_bili_auth_invalid_accepts_http_and_api_codes() -> None:
    assert is_bili_auth_invalid(401)
    assert is_bili_auth_invalid(403)
    assert is_bili_auth_invalid(200, {"code": -101})
    assert is_bili_auth_invalid(200, {"code": 412})


def test_bili_auth_invalid_ignores_success_and_non_dict_data() -> None:
    assert not is_bili_auth_invalid(200, {"code": 0})
    assert not is_bili_auth_invalid(200, None)
    assert not is_bili_auth_invalid(200, cast("dict", ["not", "a", "dict"]))


def test_extract_bili_login_cookie_merges_response_and_login_url() -> None:
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://passport.bilibili.com/"),
    )
    response.cookies.set("SESSDATA", "response-session")
    response.cookies.set("ignored_empty", "")
    login_url = (
        "https://example.test/callback?"
        "SESSDATA=query-session&bili_jct=csrf-token&ignored=value"
    )

    cookie = extract_bili_login_cookie(response, login_url)

    assert "SESSDATA=query-session" in cookie
    assert "bili_jct=csrf-token" in cookie
    assert "ignored=value" not in cookie
    assert "ignored_empty=" not in cookie


def test_has_complete_bili_login_cookie_requires_sessdata() -> None:
    assert has_complete_bili_login_cookie("SESSDATA=value; bili_jct=csrf")
    assert not has_complete_bili_login_cookie("bili_jct=csrf")


def test_parse_bili_login_qrcode_response_extracts_request() -> None:
    request = parse_bili_login_qrcode_response(
        {
            "code": 0,
            "data": {
                "url": "https://passport.example.test/qr",
                "qrcode_key": "qr-key",
            },
        }
    )

    assert request.url == "https://passport.example.test/qr"
    assert request.qrcode_key == "qr-key"


def test_parse_bili_login_qrcode_response_rejects_failures() -> None:
    with pytest.raises(ValueError, match="Bilibili QR request failed"):
        parse_bili_login_qrcode_response({"code": -1, "message": "failed"})

    with pytest.raises(ValueError, match="incomplete"):
        parse_bili_login_qrcode_response({"code": 0, "data": {"url": ""}})


def test_classify_bili_login_poll_code() -> None:
    assert classify_bili_login_poll_code(0) == "confirmed"
    assert classify_bili_login_poll_code(86038) == "expired"
    assert classify_bili_login_poll_code(86101) == "pending"
    assert classify_bili_login_poll_code(None) == "pending"


def test_bili_login_runtime_state_tracks_required_and_qr_cache() -> None:
    state = BiliLoginRuntimeState()
    expected_expires_at = 130.0
    request = LoginQrRequest(
        url="https://passport.example.test/qr",
        qrcode_key="qr-key",
    )

    mark_bili_login_required(state, required=True)
    assert state.required

    store_bili_login_qr_request(
        state,
        request,
        now=100.0,
        expires_in_seconds=30.0,
    )
    assert state.qr_url == request.url
    assert state.qrcode_key == request.qrcode_key
    assert state.expires_at == expected_expires_at
    assert is_bili_login_qr_reusable(
        state,
        now=120.0,
        poll_task_running=True,
    )
    assert not is_bili_login_qr_reusable(
        state,
        now=131.0,
        poll_task_running=True,
    )
    assert not is_bili_login_qr_reusable(
        state,
        now=120.0,
        poll_task_running=False,
    )

    assert not clear_bili_login_qr_if_matches(state, "other-key")
    assert state.qrcode_key == "qr-key"

    assert clear_bili_login_qr_if_matches(state, "qr-key")
    assert state.qr_url == ""
    assert state.qrcode_key == ""
    assert state.expires_at == 0.0


def test_bili_login_runtime_state_tracks_notice_cooldown() -> None:
    state = BiliLoginRuntimeState(last_notice_at=100.0)
    notice_sent_at = 150.0

    assert not should_send_bili_login_notice(
        state,
        now=120.0,
        cooldown_seconds=30.0,
    )
    assert should_send_bili_login_notice(
        state,
        now=120.0,
        cooldown_seconds=30.0,
        force=True,
    )
    assert should_send_bili_login_notice(
        state,
        now=130.0,
        cooldown_seconds=30.0,
    )

    mark_bili_login_notice_sent(state, now=notice_sent_at)
    assert state.last_notice_at == notice_sent_at

    reset_bili_login_notice_cooldown(state)
    assert state.last_notice_at == 0.0


def test_bili_login_notice_text_builders_include_optional_reason() -> None:
    assert build_bili_login_reason_detail("") == ""
    assert build_bili_login_reason_detail("自动检查") == "\n原因：自动检查"

    notice = build_bili_login_notice_text("自动检查")
    assert "B站动态监控登录已失效" in notice
    assert "原因：自动检查" in notice
    assert "其他机器人功能会继续正常运行" in notice

    failed = build_bili_login_qrcode_request_failed_text("用户查询")
    assert "原因：用户查询" in failed
    assert "二维码申请失败" in failed


def test_bili_login_static_notice_texts() -> None:
    assert "完整登录Cookie" in build_bili_login_cookie_incomplete_text()
    assert "Cookie已刷新" in build_bili_login_success_text()
    assert "扫码登录过程中发生错误" in build_bili_login_poll_error_text()


def test_build_bili_login_qrcode_tip_includes_login_url() -> None:
    qr_url = "https://passport.example.test/qr"

    tip = build_bili_login_qrcode_tip(qr_url)

    assert "B站登录已失效" in tip
    assert "二维码约3分钟内有效" in tip
    assert qr_url in tip


def test_build_bili_login_qrcode_message_parts_encodes_qr_image() -> None:
    parts = build_bili_login_qrcode_message_parts(
        "https://passport.example.test/qr"
    )

    assert parts.tip_text
    assert not parts.image_error
    assert parts.image_base64
