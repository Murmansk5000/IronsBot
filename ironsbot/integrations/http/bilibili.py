from typing import Any

from httpx import AsyncClient

from ironsbot.services.bilibili.auth import (
    BiliLoginPollResponse,
    LoginQrRequest,
    parse_bili_login_qrcode_response,
)
from ironsbot.services.bilibili.service import BiliFeedResponse

LIST_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?type=all"
QR_GENERATE_URL = (
    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
)
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"


async def fetch_bili_feed(client: AsyncClient, cookie: str) -> BiliFeedResponse:
    headers: dict[str, str] = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://t.bilibili.com/",
    }
    if cookie:
        headers["Cookie"] = cookie
    response = await client.get(
        LIST_URL,
        headers=headers,
        timeout=10.0,
        follow_redirects=True,
    )
    data: Any = response.json()
    return BiliFeedResponse(response.status_code, data)


async def request_bili_login_qr(client: AsyncClient) -> LoginQrRequest:
    response = await client.get(
        QR_GENERATE_URL,
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10.0,
        follow_redirects=True,
    )
    return parse_bili_login_qrcode_response(response.json())


async def poll_bili_login_qr(
    client: AsyncClient,
    qrcode_key: str,
) -> BiliLoginPollResponse:
    response = await client.get(
        QR_POLL_URL,
        params={"qrcode_key": qrcode_key},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10.0,
        follow_redirects=True,
    )
    payload = response.json()
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    return BiliLoginPollResponse(
        code=data.get("code"),
        login_url=str(data.get("url") or ""),
        cookies=dict(response.cookies.items()),
    )
