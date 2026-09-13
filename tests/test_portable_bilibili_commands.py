from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, RemoteImagePart, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.bilibili.menu import (
    DynamicDetailSelection,
    DynamicMenuResult,
)
from ironsbot.services.bilibili.service import PreparedDynamicDetail
from ironsbot.services.portable_bilibili_commands import (
    build_portable_bilibili_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions

if TYPE_CHECKING:
    from ironsbot.services.bilibili.dynamic_history import DynamicHistoryRecord
    from ironsbot.services.bilibili.menu import DynamicMenuStatus
    from ironsbot.services.bilibili.service import BilibiliService


class _FakeBilibiliService:
    status = "ok"

    async def query_dynamic_menu(self, **_kwargs: object) -> DynamicMenuResult:
        if self.status != "ok":
            return DynamicMenuResult(status=cast("DynamicMenuStatus", self.status))
        return DynamicMenuResult(
            status="ok",
            dynamic_ids=("dynamic-1", "dynamic-2"),
            prompt="动态菜单",
        )

    def select_dynamic(
        self,
        cached_ids: list[object],
        raw_text: str,
    ) -> DynamicDetailSelection:
        assert raw_text == "1"
        return DynamicDetailSelection(
            status="ok",
            record=cast("DynamicHistoryRecord", cached_ids[0]),
        )

    async def prepare_dynamic_detail(
        self,
        record: object,
    ) -> PreparedDynamicDetail:
        return PreparedDynamicDetail(
            {
                "id_str": str(record),
                "modules": {
                    "module_dynamic": {
                        "major": {
                            "opus": {
                                "summary": {"text": f"正文:{record}"},
                                "pics": [{"url": "https://example.test/image.png"}],
                            }
                        }
                    }
                },
            }
        )


def _context(text: str) -> MessageInputContext:
    actor = ActorRef(Platform.QQ_OFFICIAL, "opaque-user")
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=ConversationRef(Platform.QQ_OFFICIAL, "private", actor.id),
            message_id="message-id",
            text=text,
        ),
        mentions_bot=False,
    )


@pytest.mark.asyncio
async def test_portable_bilibili_menu_reuses_numeric_session() -> None:
    service = _FakeBilibiliService()
    sessions = PortableQuerySessions()
    notifications: list[str] = []

    async def notify(reason: str) -> None:
        notifications.append(reason)

    operation = build_portable_bilibili_operations(
        cast("BilibiliService", service),
        sessions,
        notify_auth_invalid=notify,
    )["bilibili.dynamic"]
    context = _context("动态")

    menu = cast("OutboundMessage", await operation("动态", context))
    detail = await sessions.select("2", context)

    assert cast("TextPart", menu.parts[0]).text == "动态菜单"
    assert detail is not None
    assert cast("TextPart", detail.parts[0]).text == "正文:dynamic-2"
    assert isinstance(detail.parts[1], RemoteImagePart)
    assert sessions.recognizes_selection("1", context)
    exited = await sessions.select("0", context)
    assert exited is not None
    assert cast("TextPart", exited.parts[0]).text == "已退出动态选择。"
    assert not sessions.recognizes_selection("1", context)
    assert notifications == []


@pytest.mark.asyncio
async def test_portable_bilibili_menu_reports_auth_failure() -> None:
    service = _FakeBilibiliService()
    service.status = "auth_invalid"
    sessions = PortableQuerySessions()
    notifications: list[str] = []

    async def notify(reason: str) -> None:
        notifications.append(reason)

    operation = build_portable_bilibili_operations(
        cast("BilibiliService", service),
        sessions,
        notify_auth_invalid=notify,
    )["bilibili.dynamic"]

    result = cast(
        "OutboundMessage",
        await operation("动态", _context("动态")),
    )

    assert "Cookie 已失效" in cast("TextPart", result.parts[0]).text
    assert notifications == ["用户查询动态时发现 B 站登录失效"]
