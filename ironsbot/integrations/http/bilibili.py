import logging
from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from httpx import AsyncClient

from ironsbot.services.bilibili.auth import (
    BiliLoginPollResponse,
    LoginQrRequest,
    parse_bili_login_qrcode_response,
)
from ironsbot.services.bilibili.service import BiliFeedResponse

logger = logging.getLogger(__name__)

LIST_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
SPACE_FEED_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
DYNAMIC_DETAIL_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"
OPUS_DETAIL_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/opus/detail"
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
    if not _dynamic_detail_is_truncated(data):
        return BiliFeedResponse(response.status_code, data)

    try:
        opus_response = await client.get(
            OPUS_DETAIL_URL,
            params={"id": dynamic_id},
            headers=_dynamic_headers(
                cookie,
                referer=f"https://www.bilibili.com/opus/{dynamic_id}",
            ),
            timeout=10.0,
            follow_redirects=True,
        )
        opus_data: Any = opus_response.json()
    except Exception:
        logger.exception(
            "Bilibili Opus body completion request failed: id=%s",
            dynamic_id,
        )
        return BiliFeedResponse(response.status_code, data)
    opus_body = _opus_body(opus_data)
    if (
        opus_response.status_code == HTTP_OK
        and _api_code(opus_data) == 0
        and opus_body
    ):
        data = _replace_dynamic_summary(data, opus_body)
    else:
        logger.warning(
            "Bilibili Opus body completion unavailable: id=%s http=%s code=%s",
            dynamic_id,
            opus_response.status_code,
            _api_code(opus_data),
        )
    return BiliFeedResponse(response.status_code, data)


def _api_code(payload: object) -> object:
    return payload.get("code") if isinstance(payload, Mapping) else None


def _dynamic_detail_is_truncated(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    data = payload.get("data")
    item = data.get("item") if isinstance(data, Mapping) else None
    modules = item.get("modules") if isinstance(item, Mapping) else None
    dynamic = (
        modules.get("module_dynamic") if isinstance(modules, Mapping) else None
    )
    major = dynamic.get("major") if isinstance(dynamic, Mapping) else None
    opus = major.get("opus") if isinstance(major, Mapping) else None
    summary = opus.get("summary") if isinstance(opus, Mapping) else None
    return isinstance(summary, Mapping) and summary.get("has_more") is True


def _opus_body(payload: object) -> str:
    return "\n".join(
        piece
        for paragraph in _opus_paragraphs(payload)
        if (piece := _opus_paragraph_text(paragraph))
    )


def _opus_paragraphs(payload: object) -> list[object]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    item = data.get("item") if isinstance(data, Mapping) else None
    modules = item.get("modules") if isinstance(item, Mapping) else None
    if not isinstance(modules, list):
        return []

    for module in modules:
        content = module.get("module_content") if isinstance(module, Mapping) else None
        if isinstance(content, Mapping):
            paragraphs = content.get("paragraphs")
            return paragraphs if isinstance(paragraphs, list) else []
    return []


def _opus_paragraph_text(paragraph: object) -> str:
    if not isinstance(paragraph, Mapping):
        return ""
    text = paragraph.get("text")
    nodes = text.get("nodes") if isinstance(text, Mapping) else None
    if not isinstance(nodes, list):
        return ""
    return "".join(_opus_node_text(node) for node in nodes).strip()


def _opus_node_text(node: object) -> str:
    if not isinstance(node, Mapping):
        return ""
    word = node.get("word")
    value = word.get("words") if isinstance(word, Mapping) else None
    return value if isinstance(value, str) else ""


def _replace_dynamic_summary(payload: object, body: str) -> object:
    resolved = deepcopy(payload)
    if not isinstance(resolved, dict):
        return payload
    data = resolved.get("data")
    item = data.get("item") if isinstance(data, dict) else None
    modules = item.get("modules") if isinstance(item, dict) else None
    dynamic = modules.get("module_dynamic") if isinstance(modules, dict) else None
    major = dynamic.get("major") if isinstance(dynamic, dict) else None
    opus = major.get("opus") if isinstance(major, dict) else None
    summary = opus.get("summary") if isinstance(opus, dict) else None
    if not isinstance(summary, dict):
        return payload
    summary["text"] = body
    summary["has_more"] = False
    return resolved


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
