import base64
from dataclasses import dataclass
from io import BytesIO
from typing import Literal
from urllib.parse import parse_qsl, urlparse

import httpx

AUTH_INVALID_CODES = {-101, -401, -403, 412}
LOGIN_QR_EXPIRE_SECONDS = 180
LOGIN_QR_POLL_SUCCESS_CODE = 0
LOGIN_QR_POLL_EXPIRED_CODE = 86038
LOGIN_COOKIE_KEYS = {
    "SESSDATA",
    "bili_jct",
    "DedeUserID",
    "DedeUserID__ckMd5",
    "sid",
}

BiliLoginPollStatus = Literal["confirmed", "expired", "pending"]


@dataclass(frozen=True, slots=True)
class LoginQrMessageParts:
    tip_text: str
    image_base64: str = ""
    image_error: str = ""


@dataclass(frozen=True, slots=True)
class LoginQrRequest:
    url: str
    qrcode_key: str


@dataclass(slots=True)
class BiliLoginRuntimeState:
    required: bool = False
    last_notice_at: float = 0.0
    qrcode_key: str = ""
    qr_url: str = ""
    expires_at: float = 0.0


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


def has_complete_bili_login_cookie(cookie: str) -> bool:
    return "SESSDATA=" in cookie


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


def classify_bili_login_poll_code(code: object) -> BiliLoginPollStatus:
    if code == LOGIN_QR_POLL_SUCCESS_CODE:
        return "confirmed"
    if code == LOGIN_QR_POLL_EXPIRED_CODE:
        return "expired"
    return "pending"


def mark_bili_login_required(
    state: BiliLoginRuntimeState,
    *,
    required: bool,
) -> None:
    state.required = required


def is_bili_login_qr_reusable(
    state: BiliLoginRuntimeState,
    *,
    now: float,
    poll_task_running: bool,
) -> bool:
    return bool(
        state.qr_url
        and state.expires_at > now
        and poll_task_running
    )


def store_bili_login_qr_request(
    state: BiliLoginRuntimeState,
    request: LoginQrRequest,
    *,
    now: float,
    expires_in_seconds: float = LOGIN_QR_EXPIRE_SECONDS,
) -> None:
    state.qr_url = request.url
    state.qrcode_key = request.qrcode_key
    state.expires_at = now + expires_in_seconds


def clear_bili_login_qr_if_matches(
    state: BiliLoginRuntimeState,
    qrcode_key: str,
) -> bool:
    if state.qrcode_key != qrcode_key:
        return False

    state.qrcode_key = ""
    state.qr_url = ""
    state.expires_at = 0.0
    return True


def should_send_bili_login_notice(
    state: BiliLoginRuntimeState,
    *,
    now: float,
    cooldown_seconds: float,
    force: bool = False,
) -> bool:
    return force or now - state.last_notice_at >= cooldown_seconds


def mark_bili_login_notice_sent(
    state: BiliLoginRuntimeState,
    *,
    now: float,
) -> None:
    state.last_notice_at = now


def reset_bili_login_notice_cooldown(state: BiliLoginRuntimeState) -> None:
    state.last_notice_at = 0.0


def build_bili_login_reason_detail(reason: str = "") -> str:
    return f"\n原因：{reason}" if reason else ""


def build_bili_login_notice_text(reason: str = "") -> str:
    return (
        "B站动态监控登录已失效。"
        f"{build_bili_login_reason_detail(reason)}\n"
        "其他机器人功能会继续正常运行。\n"
    )


def build_bili_login_qrcode_request_failed_text(reason: str = "") -> str:
    return (
        "B站动态监控登录已失效。"
        f"{build_bili_login_reason_detail(reason)}\n"
        "二维码申请失败，请稍后重试。\n"
        "其他机器人功能会继续正常运行。"
    )


def build_bili_login_cookie_incomplete_text() -> str:
    return (
        "B站扫码已确认，但没有取得完整登录Cookie。"
        "下次检测到登录失效时会重新发送二维码。"
    )


def build_bili_login_success_text() -> str:
    return "B站登录成功，Cookie已刷新。"


def build_bili_login_poll_error_text() -> str:
    return (
        "B站扫码登录过程中发生错误。"
        "下次检测到登录失效时会重新发送二维码。"
    )


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
