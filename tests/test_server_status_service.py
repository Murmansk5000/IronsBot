from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.services.operations.headless_errors import NotLoggedInError
from ironsbot.services.operations.server_status import ServerStatusService

if TYPE_CHECKING:
    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.operations.server_status import ServerNoticeSource


class FakeHeadless:
    def __init__(self, *, connected: bool, login_result: int = 123) -> None:
        self.connected = connected
        self.login_result = login_result
        self.available: list[tuple[str, int | None]] = []
        self.unavailable: list[tuple[str, str]] = []

    def get_game(self) -> object:
        if not self.connected:
            raise NotLoggedInError("未登录")
        return SimpleNamespace(is_logged_in=True)

    async def mark_available(
        self,
        *,
        source: str,
        user_id: int | None = None,
    ) -> None:
        self.available.append((source, user_id))

    async def mark_unavailable(self, reason: str, *, source: str) -> None:
        self.unavailable.append((source, reason))

    async def login(self) -> int:
        self.connected = True
        return self.login_result


class FakeNotices:
    def __init__(
        self,
        text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.text = text
        self.error = error

    async def fetch(self) -> str | None:
        if self.error is not None:
            raise self.error
        return self.text


def service(
    headless: FakeHeadless,
    notices: FakeNotices,
) -> ServerStatusService:
    return ServerStatusService(
        cast("HeadlessService", headless),
        cast("ServerNoticeSource", notices),
    )


@pytest.mark.asyncio
async def test_normal_status_uses_logged_in_state_as_authority() -> None:
    headless = FakeHeadless(connected=True)
    result = await service(headless, FakeNotices()).query_normal()
    assert "开服了" in result.message
    assert headless.available == [("开服了吗", None)]


@pytest.mark.asyncio
async def test_normal_status_returns_notice_while_headless_is_offline() -> None:
    headless = FakeHeadless(connected=False)
    result = await service(headless, FakeNotices("维护公告")).query_normal()
    assert result.message == "维护公告"
    assert headless.unavailable == [("开服了吗", "未登录")]


@pytest.mark.asyncio
async def test_notice_failure_does_not_hide_logged_in_state() -> None:
    result = await service(
        FakeHeadless(connected=True),
        FakeNotices(error=RuntimeError("boom")),
    ).query_normal()
    assert "公告读取失败：RuntimeError" in result.message


@pytest.mark.asyncio
async def test_admin_status_reconnects_before_querying_notice() -> None:
    headless = FakeHeadless(connected=False, login_result=456)
    result = await service(headless, FakeNotices()).query_admin()
    assert "重连结果：已登录米米号 456" in result.message
    assert headless.available[-1] == ("/开服查询重连", 456)
