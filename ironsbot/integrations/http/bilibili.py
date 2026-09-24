import logging
from collections.abc import Mapping
from typing import Any

from httpx import AsyncClient

from ironsbot.integrations.http.bilibili_body import (
    article_body,
    article_id,
    opus_body,
    opus_summary_is_truncated,
    replace_article_body,
    replace_opus_summary,
)
from ironsbot.services.bilibili.auth import (
    BiliLoginPollResponse,
    LoginQrRequest,
    parse_bili_login_qrcode_response,
)
from ironsbot.services.bilibili.service import BiliFeedResponse

LIST_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
SPACE_FEED_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
DYNAMIC_DETAIL_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
OPUS_DETAIL_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail"
ARTICLE_DETAIL_URL = "https://api.bilibili.com/x/article/view"
ACCOUNT_CARD_URL = "https://api.bilibili.com/x/web-interface/card"
HTTP_OK = 200
OPUS_STYLE_FEATURE = "itemOpusStyle"
QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
logger = logging.getLogger(__name__)


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


async def _complete_opus_body(
    client: AsyncClient,
    cookie: str,
    dynamic_id: str,
    detail: object,
) -> object:
    try:
        response = await client.get(
            OPUS_DETAIL_URL,
            params={"id": dynamic_id},
            headers=_dynamic_headers(
                cookie, referer=f"https://www.bilibili.com/opus/{dynamic_id}"
            ),
            timeout=10.0,
            follow_redirects=True,
        )
        payload = response.json()
    except Exception:
        logger.exception("Bilibili Opus completion request failed: id=%s", dynamic_id)
        return detail
    body = opus_body(payload)
    if response.status_code == HTTP_OK and _api_code(payload) == 0 and body:
        return replace_opus_summary(detail, body)
    logger.warning(
        "Bilibili Opus completion unavailable: id=%s http=%s code=%s",
        dynamic_id,
        response.status_code,
        _api_code(payload),
    )
    return detail


async def _complete_article_body(
    client: AsyncClient,
    cookie: str,
    dynamic_id: str,
    resolved_article_id: int,
    detail: object,
) -> object:
    try:
        response = await client.get(
            ARTICLE_DETAIL_URL,
            params={"id": resolved_article_id},
            headers=_dynamic_headers(
                cookie,
                referer=f"https://www.bilibili.com/read/cv{resolved_article_id}",
            ),
            timeout=10.0,
            follow_redirects=True,
        )
        payload = response.json()
    except Exception:
        logger.exception(
            "Bilibili article completion request failed: dynamic=%s article=%s",
            dynamic_id,
            resolved_article_id,
        )
        return detail
    body = article_body(payload)
    if response.status_code == HTTP_OK and _api_code(payload) == 0 and body:
        return replace_article_body(detail, body)
    logger.warning(
        "Bilibili article completion unavailable: dynamic=%s article=%s "
        "http=%s code=%s",
        dynamic_id,
        resolved_article_id,
        response.status_code,
        _api_code(payload),
    )
    return detail


def _api_code(payload: object) -> object:
    return payload.get("code") if isinstance(payload, Mapping) else None


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
    if response.status_code != HTTP_OK or _api_code(data) != 0:
        return BiliFeedResponse(response.status_code, data)
    if (resolved_article_id := article_id(data)) is not None:
        data = await _complete_article_body(
            client, cookie, dynamic_id, resolved_article_id, data
        )
    elif opus_summary_is_truncated(data):
        data = await _complete_opus_body(client, cookie, dynamic_id, data)
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
