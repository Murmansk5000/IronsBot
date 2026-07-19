# SPDX-License-Identifier: MIT
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.services.bilibili.auth import (
    BiliLoginPollResponse,
    LoginQrMessageParts,
    LoginQrRequest,
    build_bili_login_qrcode_message_parts,
    extract_bili_login_cookie,
)

if TYPE_CHECKING:
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.services.bilibili.service import BiliCookieStore

logger = logging.getLogger(__name__)
LOGIN_QR_EXPIRE_SECONDS = 180
LOGIN_QR_POLL_SUCCESS_CODE = 0
LOGIN_QR_POLL_EXPIRED_CODE = 86038
COOKIE_INCOMPLETE_NOTICE = (
    "B站扫码已确认，但没有取得完整登录Cookie。"
    "下次检测到登录失效时会重新发送二维码。"
)
LOGIN_SUCCESS_NOTICE = "B站登录成功，Cookie已刷新。"
LOGIN_POLL_ERROR_NOTICE = (
    "B站扫码登录过程中发生错误。"
    "下次检测到登录失效时会重新发送二维码。"
)


@dataclass(frozen=True, slots=True)
class BiliLoginNotice:
    text: str
    qrcode: LoginQrMessageParts | None = None


@dataclass(slots=True)
class BiliLoginState:
    required: bool = False
    last_notice_at: float = 0.0
    qrcode_key: str = ""
    qr_url: str = ""
    expires_at: float = 0.0


LoginNoticeSender = Callable[[BiliLoginNotice], Awaitable[None]]
OnlineProbe = Callable[[], bool]
LoginQrRequester = Callable[[], Awaitable[LoginQrRequest]]
LoginQrPoller = Callable[[str], Awaitable[BiliLoginPollResponse]]


@dataclass(slots=True)
class BilibiliLoginService:
    cooldown_seconds: float
    cookie_store: BiliCookieStore
    request_qr: LoginQrRequester
    poll_qr: LoginQrPoller
    spawn: TaskSpawner
    state: BiliLoginState = field(default_factory=BiliLoginState)
    poll_task: asyncio.Task[None] | None = None

    async def notify_required(
        self,
        reason: str = "",
        *,
        send_notice: LoginNoticeSender,
        is_online: OnlineProbe,
        force: bool = False,
    ) -> None:
        self.state.required = True
        now = time.time()
        if (
            not force
            and now - self.state.last_notice_at < self.cooldown_seconds
        ):
            return
        if not is_online():
            logger.warning("no bot online, cannot send Bilibili login QR")
            return

        try:
            qrcode = await self._request_qrcode(send_notice)
        except Exception:
            logger.exception("Bilibili QR request failed")
            self.state.last_notice_at = now
            await send_notice(BiliLoginNotice(_login_request_failed(reason)))
            return

        self.state.last_notice_at = now
        await send_notice(BiliLoginNotice(_login_required(reason), qrcode))

    async def _request_qrcode(
        self,
        send_notice: LoginNoticeSender,
    ) -> LoginQrMessageParts:
        now = time.time()
        poll_task = self.poll_task
        if (
            self.state.qr_url
            and self.state.expires_at > now
            and poll_task is not None
            and not poll_task.done()
        ):
            return build_bili_login_qrcode_message_parts(self.state.qr_url)

        if poll_task is not None and not poll_task.done():
            poll_task.cancel()

        request = await self.request_qr()
        self.state.qr_url = request.url
        self.state.qrcode_key = request.qrcode_key
        self.state.expires_at = now + LOGIN_QR_EXPIRE_SECONDS
        self.poll_task = self.spawn(
            self._poll_login(request.qrcode_key, send_notice),
            name="bilibili-login-poll",
        )
        return build_bili_login_qrcode_message_parts(request.url)

    async def _poll_login(
        self,
        qrcode_key: str,
        send_notice: LoginNoticeSender,
    ) -> None:
        try:
            for _ in range(36):
                await asyncio.sleep(5)
                poll = await self.poll_qr(qrcode_key)
                if poll.code == LOGIN_QR_POLL_SUCCESS_CODE:
                    cookie = extract_bili_login_cookie(
                        poll.cookies,
                        poll.login_url,
                    )
                    if "SESSDATA=" not in cookie:
                        await send_notice(
                            BiliLoginNotice(COOKIE_INCOMPLETE_NOTICE)
                        )
                        return
                    self.cookie_store.save(cookie)
                    self.state.required = False
                    logger.info("Bilibili cookie refreshed")
                    await send_notice(BiliLoginNotice(LOGIN_SUCCESS_NOTICE))
                    return
                if poll.code == LOGIN_QR_POLL_EXPIRED_CODE:
                    break

            logger.info("Bilibili login QR expired")
            self.state.last_notice_at = 0.0
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Bilibili QR polling failed")
            await send_notice(BiliLoginNotice(LOGIN_POLL_ERROR_NOTICE))
        finally:
            if self.state.qrcode_key == qrcode_key:
                self.state.qrcode_key = ""
                self.state.qr_url = ""
                self.state.expires_at = 0.0
            if self.poll_task is asyncio.current_task():
                self.poll_task = None


def _reason_detail(reason: str) -> str:
    return f"\n原因：{reason}" if reason else ""


def _login_required(reason: str) -> str:
    return (
        "B站动态监控登录已失效。"
        f"{_reason_detail(reason)}\n"
        "其他机器人功能会继续正常运行。\n"
    )


def _login_request_failed(reason: str) -> str:
    return (
        "B站动态监控登录已失效。"
        f"{_reason_detail(reason)}\n"
        "二维码申请失败，请稍后重试。\n"
        "其他机器人功能会继续正常运行。"
    )
