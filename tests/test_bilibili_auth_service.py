import httpx
import pytest

from ironsbot.services.bilibili.auth import (
    build_bili_login_qrcode_message_parts,
    build_bili_login_qrcode_tip,
    classify_bili_login_poll_code,
    extract_bili_login_cookie,
    has_complete_bili_login_cookie,
    is_bili_auth_invalid,
    parse_bili_login_qrcode_response,
)


def test_bili_auth_invalid_accepts_http_and_api_codes() -> None:
    assert is_bili_auth_invalid(401)
    assert is_bili_auth_invalid(403)
    assert is_bili_auth_invalid(200, {"code": -101})
    assert is_bili_auth_invalid(200, {"code": 412})


def test_bili_auth_invalid_ignores_success_and_non_dict_data() -> None:
    assert not is_bili_auth_invalid(200, {"code": 0})
    assert not is_bili_auth_invalid(200, None)
    assert not is_bili_auth_invalid(200, ["not", "a", "dict"])


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
