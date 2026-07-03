import asyncio
import time

import httpx
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.log import logger

from ironsbot.services.bilibili.auth import (
    BiliLoginRuntimeState,
    build_bili_login_cookie_incomplete_text,
    build_bili_login_notice_text,
    build_bili_login_poll_error_text,
    build_bili_login_qrcode_message_parts,
    build_bili_login_qrcode_request_failed_text,
    build_bili_login_success_text,
    classify_bili_login_poll_code,
    clear_bili_login_qr_if_matches,
    extract_bili_login_cookie,
    has_complete_bili_login_cookie,
    is_bili_login_qr_reusable,
    mark_bili_login_notice_sent,
    mark_bili_login_required,
    parse_bili_login_qrcode_response,
    reset_bili_login_notice_cooldown,
    should_send_bili_login_notice,
    store_bili_login_qr_request,
)
from ironsbot.services.bilibili.cache import save_new_cookie
from ironsbot.services.bilibili.permissions import get_bili_superuser_uids

from .bot_access import get_first_bot
from .config import get_bili_config

_login_state = BiliLoginRuntimeState()
_login_poll_task: asyncio.Task[None] | None = None


def is_bili_login_required() -> bool:
    return _login_state.required


def _set_bili_login_required(required: bool) -> None:
    mark_bili_login_required(_login_state, required=required)


async def _send_private_to_superusers(
    message: str | Message,
    bot: Bot | None = None,
    user_ids: list[int] | None = None,
) -> None:
    from ironsbot.shared.messaging import send_broadcast_message

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
        subscription_key="admin_notice",
    )


def _build_login_qrcode_message(qr_url: str) -> Message:
    parts = build_bili_login_qrcode_message_parts(qr_url)
    if parts.image_base64:
        return Message([
            MessageSegment.image(f"base64://{parts.image_base64}"),
            MessageSegment.text("\n" + parts.tip_text),
        ])

    if parts.image_error:
        logger.warning(
            f"failed to build Bilibili login QR image: {parts.image_error}"
        )
    return Message(parts.tip_text)


async def request_bili_login_qrcode(
    bot: Bot,
    requester_id: int | None = None,
) -> Message:
    global _login_poll_task

    now = time.time()
    poll_task_running = bool(
        _login_poll_task and not _login_poll_task.done()
    )
    if is_bili_login_qr_reusable(
        _login_state,
        now=now,
        poll_task_running=poll_task_running,
    ):
        return _build_login_qrcode_message(_login_state.qr_url)

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

    qr_request = parse_bili_login_qrcode_response(response.json())
    store_bili_login_qr_request(
        _login_state,
        qr_request,
        now=now,
    )
    _login_poll_task = asyncio.create_task(
        _poll_bili_login(
            bot=bot,
            qrcode_key=qr_request.qrcode_key,
            requester_id=requester_id,
        )
    )

    return _build_login_qrcode_message(qr_request.url)


async def send_bili_login_qrcode_to_superusers(
    reason: str = "",
    force: bool = False,
) -> None:
    _set_bili_login_required(True)
    now = time.time()

    if not should_send_bili_login_notice(
        _login_state,
        now=now,
        cooldown_seconds=get_bili_config().login_notice_cooldown_seconds,
        force=force,
    ):
        return

    bot = get_first_bot()
    if not bot:
        logger.warning("no bot online, cannot send Bilibili login QR")
        return

    try:
        qr_message = await request_bili_login_qrcode(bot)
        mark_bili_login_notice_sent(_login_state, now=now)
    except Exception as e:
        logger.error(f"Bilibili QR request failed: {e}")
        mark_bili_login_notice_sent(_login_state, now=now)
        await _send_private_to_superusers(
            build_bili_login_qrcode_request_failed_text(reason),
            bot=bot,
        )
        return

    await _send_private_to_superusers(
        Message([
            MessageSegment.text(build_bili_login_notice_text(reason)),
            *qr_message,
        ]),
        bot=bot,
    )


async def _poll_bili_login(
    bot: Bot,
    qrcode_key: str,
    requester_id: int | None = None,
) -> None:
    global _login_poll_task

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
                poll_status = classify_bili_login_poll_code(
                    poll_data.get("code")
                )

                if poll_status == "confirmed":
                    new_cookie = extract_bili_login_cookie(
                        poll_res,
                        poll_data.get("url", ""),
                    )

                    if not has_complete_bili_login_cookie(new_cookie):
                        await _send_private_to_superusers(
                            build_bili_login_cookie_incomplete_text(),
                            bot=bot,
                            user_ids=[requester_id] if requester_id else None,
                        )
                        return

                    save_new_cookie(new_cookie)
                    _set_bili_login_required(False)
                    logger.info("Bilibili cookie refreshed")
                    await _send_private_to_superusers(
                        build_bili_login_success_text(),
                        bot=bot,
                    )
                    return

                if poll_status == "expired":
                    break

            logger.info("Bilibili login QR expired")
            reset_bili_login_notice_cooldown(_login_state)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Bilibili QR polling failed: {e}")
        await _send_private_to_superusers(
            build_bili_login_poll_error_text(),
            bot=bot,
            user_ids=[requester_id] if requester_id else None,
        )
    finally:
        clear_bili_login_qr_if_matches(_login_state, qrcode_key)

        if _login_poll_task is asyncio.current_task():
            _login_poll_task = None
