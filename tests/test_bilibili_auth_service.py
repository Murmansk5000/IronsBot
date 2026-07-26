from __future__ import annotations

from typing import TYPE_CHECKING, cast

import httpx
import pytest

from ironsbot.integrations.http.bilibili import fetch_bili_account_name
from ironsbot.integrations.storage.bilibili_cookie import FileBiliCookieStore
from ironsbot.services.bilibili import login
from ironsbot.services.bilibili.auth import (
    BiliLoginPollResponse,
    LoginQrRequest,
    build_bili_login_qrcode_message_parts,
    extract_bili_login_cookie,
    is_bili_auth_invalid,
    parse_bili_login_qrcode_response,
)
from ironsbot.services.bilibili.login import (
    BilibiliLoginService,
    BiliLoginNotice,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from pathlib import Path

    from pytest import MonkeyPatch


def test_bili_auth_invalid_accepts_http_and_api_codes() -> None:
    assert is_bili_auth_invalid(401)
    assert is_bili_auth_invalid(403)
    assert is_bili_auth_invalid(200, {"code": -101})
    assert is_bili_auth_invalid(200, {"code": 412})
    assert not is_bili_auth_invalid(200, {"code": 0})
    assert not is_bili_auth_invalid(200, None)
    assert not is_bili_auth_invalid(
        200,
        cast("dict", ["not", "a", "dict"]),
    )


@pytest.mark.asyncio
async def test_fetch_bili_account_name_uses_public_card_name() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["mid"] == "1310714247"
        assert request.url.params["photo"] == "true"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "card": {
                        "mid": "1310714247",
                        "name": "赛尔号官号",
                    }
                },
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        name = await fetch_bili_account_name(client, 1310714247)

    assert name == "赛尔号官号"


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

    cookie = extract_bili_login_cookie(response.cookies, login_url)

    assert "SESSDATA=query-session" in cookie
    assert "bili_jct=csrf-token" in cookie
    assert "ignored=value" not in cookie
    assert "ignored_empty=" not in cookie


def test_parse_bili_login_qrcode_response() -> None:
    request = parse_bili_login_qrcode_response(
        {
            "code": 0,
            "data": {
                "url": "https://passport.example.test/qr",
                "qrcode_key": "qr-key",
            },
        }
    )
    assert request.qrcode_key == "qr-key"

    with pytest.raises(ValueError, match="Bilibili QR request failed"):
        parse_bili_login_qrcode_response({"code": -1})
    with pytest.raises(ValueError, match="incomplete"):
        parse_bili_login_qrcode_response({"code": 0, "data": {"url": ""}})


def test_build_bili_login_qrcode_message_parts_encodes_qr_image() -> None:
    parts = build_bili_login_qrcode_message_parts(
        "https://passport.example.test/qr"
    )

    assert "二维码约3分钟内有效" in parts.tip_text
    assert not parts.image_error
    assert parts.image_base64


@pytest.mark.asyncio
async def test_bili_login_service_owns_qr_poll_and_cookie_refresh(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    notices: list[BiliLoginNotice] = []

    async def request_qr() -> LoginQrRequest:
        return LoginQrRequest(
            url="https://passport.example.test/qr",
            qrcode_key="qr-key",
        )

    async def poll_qr(_key: str) -> BiliLoginPollResponse:
        return BiliLoginPollResponse(
            code=0,
            login_url="",
            cookies={"SESSDATA": "session"},
        )

    async def no_sleep(_seconds: float) -> None:
        return None

    async def send_notice(notice: BiliLoginNotice) -> None:
        notices.append(notice)

    monkeypatch.setattr(login.asyncio, "sleep", no_sleep)
    cookie_store = FileBiliCookieStore(tmp_path / "cookie.txt")
    service = BilibiliLoginService(
        0,
        cookie_store,
        request_qr,
        poll_qr,
        build_test_runtime().tasks.create,
    )
    await service.notify_required(
        "测试",
        send_notice=send_notice,
        is_online=lambda: True,
    )

    task = service.poll_task
    assert task is not None
    await task

    assert notices[0].qrcode is not None
    assert notices[-1].text == login.LOGIN_SUCCESS_NOTICE
    assert cookie_store.load() == "SESSDATA=session"
    assert not service.state.required
