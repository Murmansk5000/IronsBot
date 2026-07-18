import asyncio
import time

import httpx
from nonebot.adapters.onebot.v11 import Bot, Message, MessageSegment
from nonebot.log import logger

from ironsbot.services.bilibili.auth import (
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
from ironsbot.services.bilibili.resources import BilibiliResources


def _set_bili_login_required(
    resources: BilibiliResources,
    required: bool,
) -> None:
    mark_bili_login_required(resources.login_state, required=required)


async def _send_private_to_superusers(
    resources: BilibiliResources,
    message: str | Message,
    bot: Bot | None = None,
    user_ids: list[int] | None = None,
) -> None:
    admin_notices = resources.admin_notices
    if user_ids is None:
        await admin_notices.send(
            message,
            bot=bot,
            action_name="Bilibili login notice",
            interval_seconds=1.2,
            subscription_key="bili_login_notice",
        )
        return

    if not user_ids:
        logger.warning("Bilibili monitor has no superusers for login notice")
        return

    from ironsbot.shared.messaging import send_broadcast_message

    await send_broadcast_message(
        admin_notices.delivery,
        message,
        private_user_ids=user_ids,
        bot=bot,
        action_name="Bilibili login notice",
        interval_seconds=1.2,
        subscription_key="bili_login_notice",
    )


def _build_login_qrcode_message(qr_url: str) -> Message:
    parts = build_bili_login_qrcode_message_parts(qr_url)
    if parts.image_base64:
        return Message(
            [
                MessageSegment.image(f"base64://{parts.image_base64}"),
                MessageSegment.text("\n" + parts.tip_text),
            ]
        )

    if parts.image_error:
        logger.warning(f"failed to build Bilibili login QR image: {parts.image_error}")
    return Message(parts.tip_text)


async def request_bili_login_qrcode(
    resources: BilibiliResources,
    bot: Bot,
    requester_id: int | None = None,
) -> Message:
    now = time.time()
    poll_task = resources.login_poll_task
    poll_task_running = bool(poll_task and not poll_task.done())
    if is_bili_login_qr_reusable(
        resources.login_state,
        now=now,
        poll_task_running=poll_task_running,
    ):
        return _build_login_qrcode_message(resources.login_state.qr_url)

    if poll_task and not poll_task.done():
        poll_task.cancel()

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=10.0,
        follow_redirects=True,
    ) as client:
        response = await client.get(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
        )

    qr_request = parse_bili_login_qrcode_response(response.json())
    store_bili_login_qr_request(
        resources.login_state,
        qr_request,
        now=now,
    )
    resources.login_poll_task = asyncio.create_task(
        _poll_bili_login(
            resources=resources,
            bot=bot,
            qrcode_key=qr_request.qrcode_key,
            requester_id=requester_id,
        )
    )

    return _build_login_qrcode_message(qr_request.url)


async def send_bili_login_qrcode_to_superusers(
    resources: BilibiliResources,
    reason: str = "",
    force: bool = False,
) -> None:
    _set_bili_login_required(resources, True)
    now = time.time()

    if not should_send_bili_login_notice(
        resources.login_state,
        now=now,
        cooldown_seconds=resources.config.login_notice_cooldown_seconds,
        force=force,
    ):
        return

    bot = resources.admin_notices.delivery.bot_router.default_bot()
    if not bot:
        logger.warning("no bot online, cannot send Bilibili login QR")
        return

    try:
        qr_message = await request_bili_login_qrcode(
            resources,
            bot,
        )
        mark_bili_login_notice_sent(resources.login_state, now=now)
    except Exception as e:
        logger.error(f"Bilibili QR request failed: {e}")
        mark_bili_login_notice_sent(resources.login_state, now=now)
        await _send_private_to_superusers(
            resources,
            build_bili_login_qrcode_request_failed_text(reason),
        )
        return

    await _send_private_to_superusers(
        resources,
        Message(
            [
                MessageSegment.text(build_bili_login_notice_text(reason)),
                *qr_message,
            ]
        ),
    )


async def _poll_bili_login(
    resources: BilibiliResources,
    bot: Bot,
    qrcode_key: str,
    requester_id: int | None = None,
) -> None:
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10.0,
            follow_redirects=True,
        ) as client:
            for _ in range(36):
                await asyncio.sleep(5)

                poll_res = await client.get(
                    "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                    params={"qrcode_key": qrcode_key},
                )
                poll_data = poll_res.json().get("data", {})
                poll_status = classify_bili_login_poll_code(poll_data.get("code"))

                if poll_status == "confirmed":
                    new_cookie = extract_bili_login_cookie(
                        poll_res,
                        poll_data.get("url", ""),
                    )

                    if not has_complete_bili_login_cookie(new_cookie):
                        await _send_private_to_superusers(
                            resources,
                            build_bili_login_cookie_incomplete_text(),
                            bot=bot if requester_id else None,
                            user_ids=[requester_id] if requester_id else None,
                        )
                        return

                    resources.cookie_store.save(new_cookie)
                    _set_bili_login_required(resources, False)
                    logger.info("Bilibili cookie refreshed")
                    await _send_private_to_superusers(
                        resources,
                        build_bili_login_success_text(),
                        bot=bot if requester_id else None,
                    )
                    return

                if poll_status == "expired":
                    break

            logger.info("Bilibili login QR expired")
            reset_bili_login_notice_cooldown(resources.login_state)

    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Bilibili QR polling failed: {e}")
        await _send_private_to_superusers(
            resources,
            build_bili_login_poll_error_text(),
            bot=bot if requester_id else None,
            user_ids=[requester_id] if requester_id else None,
        )
    finally:
        clear_bili_login_qr_if_matches(resources.login_state, qrcode_key)

        if resources.login_poll_task is asyncio.current_task():
            resources.login_poll_task = None
