# SPDX-License-Identifier: MIT
from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qsl, urlparse

if TYPE_CHECKING:
    from collections.abc import Mapping

AUTH_INVALID_CODES = {-101, -401, -403, 412}
LOGIN_COOKIE_KEYS = {
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
}


@dataclass(frozen=True, slots=True)
class LoginQrMessageParts:
    tip_text: str
    image_base64: str = ""
    image_error: str = ""


@dataclass(frozen=True, slots=True)
class LoginQrRequest:
    url: str
    qrcode_key: str


@dataclass(frozen=True, slots=True)
class BiliLoginPollResponse:
    code: object
    login_url: str
    cookies: dict[str, str]


def is_bili_auth_invalid(
    status_code: int,
    data: object = None,
) -> bool:
    if status_code in {401, 403}:
        return True
    return isinstance(data, dict) and data.get("code") in AUTH_INVALID_CODES


def extract_bili_login_cookie(
    response_cookies: Mapping[str, str],
    login_url: str = "",
) -> str:
    cookies = {
        key: value
        for key, value in response_cookies.items()
        if value
    }
    if login_url:
        cookies.update(
            {
                key: value
                for key, value in parse_qsl(
                    urlparse(login_url).query,
                    keep_blank_values=False,
                )
                if key in LOGIN_COOKIE_KEYS and value
            }
        )
    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def parse_bili_login_qrcode_response(data: object) -> LoginQrRequest:
    if not isinstance(data, dict) or data.get("code") != 0:
        msg = f"Bilibili QR request failed: {data}"
        raise ValueError(msg)

    qr_data = data.get("data", {})
    if not isinstance(qr_data, dict):
        msg = "Bilibili QR response is incomplete"
        raise TypeError(msg)

    qr_url = str(qr_data.get("url") or "").strip()
    qrcode_key = str(qr_data.get("qrcode_key") or "").strip()
    if not qr_url or not qrcode_key:
        msg = "Bilibili QR response is incomplete"
        raise ValueError(msg)
    return LoginQrRequest(url=qr_url, qrcode_key=qrcode_key)


def build_bili_login_qrcode_message_parts(qr_url: str) -> LoginQrMessageParts:
    tip_text = (
        "B站登录已失效，需要重新登录。\n"
        "请使用B站App扫码；确认后机器人会自动保存Cookie。\n"
        "二维码约3分钟内有效，过期后下次检测到登录失效会重新发送。\n"
        "不扫码只会影响B站动态监控，其他机器人功能不受影响。\n"
        "如果图片无法显示，可复制下面的登录链接到二维码工具中生成：\n"
        f"{qr_url}"
    )
    try:
        import qrcode

        image: Any = qrcode.make(qr_url)
        image_bytes = BytesIO()
        image.save(image_bytes, format="PNG")
        image_base64 = base64.b64encode(image_bytes.getvalue()).decode("ascii")
    except Exception as error:  # noqa: BLE001
        return LoginQrMessageParts(
            tip_text=tip_text,
            image_error=str(error),
        )
    return LoginQrMessageParts(
        tip_text=tip_text,
        image_base64=image_base64,
    )
