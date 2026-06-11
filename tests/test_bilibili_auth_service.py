import httpx

from ironsbot.services.bilibili.auth import (
    extract_bili_login_cookie,
    is_bili_auth_invalid,
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
