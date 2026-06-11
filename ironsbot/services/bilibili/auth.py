import base64
from dataclasses import dataclass
from io import BytesIO
from urllib.parse import parse_qsl, urlparse

import httpx

AUTH_INVALID_CODES = {-101, -401, -403, 412}
LOGIN_QR_EXPIRE_SECONDS = 180
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


def is_bili_auth_invalid(
    status_code: int,
    data: dict | None = None,
) -> bool:
    if status_code in {401, 403}:
        return True

    if not isinstance(data, dict):
        return False

    return data.get("code") in AUTH_INVALID_CODES


def extract_bili_login_cookie(
    response: httpx.Response,
    login_url: str = "",
) -> str:
    cookies: dict[str, str] = {
        key: value
        for key, value in response.cookies.items()
        if value
    }

    if login_url:
        query_items = parse_qsl(
            urlparse(login_url).query,
            keep_blank_values=False,
        )
        cookies.update(
            {
                key: value
                for key, value in query_items
                if key in LOGIN_COOKIE_KEYS and value
            }
        )

    return "; ".join(f"{key}={value}" for key, value in cookies.items())


def build_bili_login_qrcode_tip(qr_url: str) -> str:
    return (
        "B站登录已失效，需要重新登录。\n"
        "请使用B站App扫码；确认后机器人会自动保存Cookie。\n"
        "二维码约3分钟内有效，过期后下次检测到登录失效会重新发送。\n"
        "不扫码只会影响B站动态监控，其他机器人功能不受影响。\n"
        "如果图片无法显示，可复制下面的登录链接到二维码工具中生成：\n"
        f"{qr_url}"
    )


def build_bili_login_qrcode_message_parts(qr_url: str) -> LoginQrMessageParts:
    tip_text = build_bili_login_qrcode_tip(qr_url)
    try:
        import qrcode

        image = qrcode.make(qr_url)
        image_bytes = BytesIO()
        image.save(image_bytes, format="PNG")
        image_base64 = base64.b64encode(image_bytes.getvalue()).decode("ascii")
    except Exception as e:  # noqa: BLE001
        return LoginQrMessageParts(
            tip_text=tip_text,
            image_error=str(e),
        )

    return LoginQrMessageParts(
        tip_text=tip_text,
        image_base64=image_base64,
    )
