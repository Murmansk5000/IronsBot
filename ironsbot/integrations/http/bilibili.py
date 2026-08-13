from typing import Any

from httpx import AsyncClient

from ironsbot.services.bilibili.auth import (
    BiliLoginPollResponse,
    LoginQrRequest,
    parse_bili_login_qrcode_response,
)
from ironsbot.services.bilibili.service import BiliFeedResponse

LIST_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
SPACE_FEED_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
DYNAMIC_DETAIL_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
ACCOUNT_CARD_URL = "https://api.bilibili.com/x/web-interface/card"
HTTP_OK = 200
OPUS_STYLE_FEATURE = "itemOpusStyle"
QR_GENERATE_URL = (
    "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
)
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"


async def fetch_bili_feed(client: AsyncClient, cookie: str) -> BiliFeedResponse:
    headers = _dynamic_headers(cookie, referer="https://t.bilibili.com/")
    response = await client.get(
        LIST_URL,
        params={"type": "all", "features": OPUS_STYLE_FEATURE},
        headers=headers,
        timeout=10.0,
        follow_redirects=True,
    )
    data: Any = response.json()
    return BiliFeedResponse(response.status_code, data)


async def fetch_bili_dynamic_detail(
    client: AsyncClient,
    cookie: str,
    dynamic_id: str,
) -> BiliFeedResponse:
    response = await client.get(
        DYNAMIC_DETAIL_URL,
        params={"id": dynamic_id, "features": OPUS_STYLE_FEATURE},
        headers=_dynamic_headers(
            cookie,
            referer=f"https://t.bilibili.com/{dynamic_id}",
        ),
        timeout=10.0,
        follow_redirects=True,
    )
    data: Any = response.json()
    return BiliFeedResponse(response.status_code, data)


async def fetch_bili_space_feed(
    client: AsyncClient,
    cookie: str,
    uid: int,
    offset: str = "",
) -> BiliFeedResponse:
    response = await client.get(
        SPACE_FEED_URL,
        params={
            "host_mid": int(uid),
            "offset": offset,
            "features": OPUS_STYLE_FEATURE,
        },
        headers=_dynamic_headers(
            cookie,
            referer=f"https://space.bilibili.com/{int(uid)}/dynamic",
        ),
        timeout=10.0,
        follow_redirects=True,
    )
    data: Any = response.json()
    return BiliFeedResponse(response.status_code, data)


def _dynamic_headers(cookie: str, *, referer: str) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": referer,
    }
    if cookie:
        headers["Cookie"] = cookie
    return headers


async def fetch_bili_account_name(
    client: AsyncClient,
    uid: int,
) -> str | None:
    response = await client.get(
        ACCOUNT_CARD_URL,
        params={"mid": int(uid), "photo": "true"},
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": f"https://space.bilibili.com/{int(uid)}/",
        },
        timeout=10.0,
        follow_redirects=True,
    )
    payload: Any = response.json()
    if (
        response.status_code != HTTP_OK
        or not isinstance(payload, dict)
        or payload.get("code") != 0
    ):
        return None
    data = payload.get("data")
    card = data.get("card") if isinstance(data, dict) else None
    if not isinstance(card, dict) or str(card.get("mid")) != str(int(uid)):
        return None
    name = str(card.get("name") or "").strip()
    return name or None


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
