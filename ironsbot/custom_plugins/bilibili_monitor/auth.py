import asyncio
import base64
import time
from io import BytesIO
from urllib.parse import parse_qsl, urlparse

import httpx
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.log import logger

from ironsbot.custom_plugins.message_actions import send_broadcast_message

from .bot_access import get_first_bot
from .cache import save_new_cookie
from .config import get_bili_config
from .permissions import get_bili_superuser_uids
from .state import (
    AUTH_INVALID_CODES,
    LOGIN_COOKIE_KEYS,
    LOGIN_QR_EXPIRE_SECONDS,
)

_bili_login_required = False
_last_login_notice_at = 0.0
_login_poll_task: asyncio.Task[None] | None = None
_login_qrcode_key = ""
_login_qr_url = ""
_login_expires_at = 0.0


def is_bili_login_required() -> bool:
    return _bili_login_required


def is_bili_auth_invalid(
    status_code: int,
    data: dict | None = None,
) -> bool:
    if status_code in {401, 403}:
        return True

    if not isinstance(data, dict):
        return False

    return data.get("code") in AUTH_INVALID_CODES


def _set_bili_login_required(required: bool) -> None:
    global _bili_login_required
    _bili_login_required = required


def _extract_bili_login_cookie(
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
        for key, value in query_items:
            if key in LOGIN_COOKIE_KEYS and value:
                cookies[key] = value

    return "; ".join(f"{key}={value}" for key, value in cookies.items())


async def _send_private_to_superusers(
    message: str | Message,
    bot: Bot | None = None,
    user_ids: list[int] | None = None,
) -> None:
    target_user_ids = user_ids or get_bili_superuser_uids()

    if not target_user_ids:
        logger.warning("Bilibili monitor has no superusers for login notice")
        return

    await send_broadcast_message(
        message,
        private_user_ids=target_user_ids,
        bot=bot or get_first_bot(),
        action_name="Bilibili login notice",
        interval_seconds=1.2,
    )


def _build_login_qrcode_message(qr_url: str) -> Message:
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

        image = qrcode.make(qr_url)
        image_bytes = BytesIO()
        image.save(image_bytes, format="PNG")
        image_base64 = base64.b64encode(image_bytes.getvalue()).decode("ascii")

        return Message([
            MessageSegment.image(f"base64://{image_base64}"),
            MessageSegment.text("\n" + tip_text),
        ])
    except Exception as e:
        logger.warning(f"failed to build Bilibili login QR image: {e}")
        return Message(tip_text)


async def request_bili_login_qrcode(
    bot: Bot,
    requester_id: int | None = None,
) -> Message:
    global _login_expires_at
    global _login_poll_task
    global _login_qr_url
    global _login_qrcode_key

    now = time.time()
    if (
        _login_qr_url
        and _login_expires_at > now
        and _login_poll_task
        and not _login_poll_task.done()
    ):
        return _build_login_qrcode_message(_login_qr_url)

    if _login_poll_task and not _login_poll_task.done():
        _login_poll_task.cancel()

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(
            "https://passport.bilibili.com/"
            "x/passport-login/web/qrcode/generate"
        )

    result = response.json()
    if result.get("code") != 0:
        raise RuntimeError(f"Bilibili QR request failed: {result}")

    qr_data = result.get("data", {})
    qr_url = qr_data.get("url")
    qrcode_key = qr_data.get("qrcode_key")
    if not qr_url or not qrcode_key:
        raise RuntimeError("Bilibili QR response is incomplete")

    _login_qr_url = qr_url
    _login_qrcode_key = qrcode_key
    _login_expires_at = now + LOGIN_QR_EXPIRE_SECONDS
    _login_poll_task = asyncio.create_task(
        _poll_bili_login(
            bot=bot,
            qrcode_key=qrcode_key,
            requester_id=requester_id,
        )
    )

    return _build_login_qrcode_message(qr_url)


async def send_bili_login_qrcode_to_superusers(
    reason: str = "",
    force: bool = False,
) -> None:
    global _last_login_notice_at

    _set_bili_login_required(True)
    now = time.time()

    if (
        not force
        and now
        - _last_login_notice_at
        < get_bili_config().login_notice_cooldown_seconds
    ):
        return

    bot = get_first_bot()
    if not bot:
        logger.warning("no bot online, cannot send Bilibili login QR")
        return

    try:
        qr_message = await request_bili_login_qrcode(bot)
        _last_login_notice_at = now
    except Exception as e:
        logger.error(f"Bilibili QR request failed: {e}")
        _last_login_notice_at = now
        detail = f"\n原因：{reason}" if reason else ""
        await _send_private_to_superusers(
            "B站动态监控登录已失效。"
            f"{detail}\n"
            "二维码申请失败，请稍后重试。\n"
            "其他机器人功能会继续正常运行。",
            bot=bot,
        )
        return

    detail = f"\n原因：{reason}" if reason else ""
    await _send_private_to_superusers(
        Message([
            MessageSegment.text(
                "B站动态监控登录已失效。"
                f"{detail}\n"
                "其他机器人功能会继续正常运行。\n"
            ),
            *qr_message,
        ]),
        bot=bot,
    )


async def _poll_bili_login(
    bot: Bot,
    qrcode_key: str,
    requester_id: int | None = None,
) -> None:
    global _last_login_notice_at
    global _login_expires_at
    global _login_poll_task
    global _login_qr_url
    global _login_qrcode_key

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            for _ in range(36):
                await asyncio.sleep(5)

                poll_res = await client.get(
                    "https://passport.bilibili.com/"
                    "x/passport-login/web/qrcode/poll",
                    params={"qrcode_key": qrcode_key},
                )
                poll_data = poll_res.json().get("data", {})
                poll_code = poll_data.get("code")

                if poll_code == 0:
                    new_cookie = _extract_bili_login_cookie(
                        poll_res,
                        poll_data.get("url", ""),
                    )

                    if "SESSDATA=" not in new_cookie:
                        await _send_private_to_superusers(
                            "B站扫码已确认，但没有取得完整登录Cookie。"
                            "下次检测到登录失效时会重新发送二维码。",
                            bot=bot,
                            user_ids=[requester_id] if requester_id else None,
                        )
                        return

                    save_new_cookie(new_cookie)
                    _set_bili_login_required(False)
                    logger.info("Bilibili cookie refreshed")
                    await _send_private_to_superusers(
                        "B站登录成功，Cookie已刷新。",
                        bot=bot,
                    )
                    return

                if poll_code == 86038:
                    break

            logger.info("Bilibili login QR expired")
            _last_login_notice_at = 0.0

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Bilibili QR polling failed: {e}")
        await _send_private_to_superusers(
            "B站扫码登录过程中发生错误。"
            "下次检测到登录失效时会重新发送二维码。",
            bot=bot,
            user_ids=[requester_id] if requester_id else None,
        )
    finally:
        if _login_qrcode_key == qrcode_key:
            _login_qrcode_key = ""
            _login_qr_url = ""
            _login_expires_at = 0.0

        if _login_poll_task is asyncio.current_task():
            _login_poll_task = None
