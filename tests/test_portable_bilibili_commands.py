from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.bilibili import BiliConfig
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
from ironsbot.services.portable_reply import PortableReply

if TYPE_CHECKING:
    from ironsbot.services.bilibili.dynamic_history import DynamicHistoryRecord
    from ironsbot.services.bilibili.menu import DynamicMenuStatus
    from ironsbot.services.bilibili.service import BilibiliService


class _FakeBilibiliService:
    status = "ok"
    config = BiliConfig()
    image_collage = None

    def __init__(self) -> None:
        self.targets = _FakeBiliTargets()
        self.history = SimpleNamespace(get=lambda _id: SimpleNamespace(uid=123))

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


class _FakeBiliTargets:
    def query_uids(self, _actor: ActorRef, _conversation: ConversationRef) -> list[int]:
        return [123]

    async def account_summary(self, conversation: ConversationRef) -> str:
        return f"账号:{conversation.account_id}:{conversation.id}"

    async def update_push_mode(
        self,
        conversation: ConversationRef,
        account_ref: str,
        raw_mode: str,
    ) -> str:
        return f"模式:{conversation.account_id}:{account_ref}:{raw_mode}"


def _context(text: str) -> MessageInputContext:
    actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "opaque-user",
        account_id="example-app",
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL,
                "private",
                actor.id,
                account_id=actor.account_id,
            ),
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
        refresh_now=lambda: _refresh_result("完成"),
    )["bilibili.dynamic"]
    context = _context("动态")

    menu = cast("OutboundMessage", await operation("动态", context))
    detail = await sessions.select("2", context, allow_deferred=True)

    assert cast("TextPart", menu.parts[0]).text == "动态菜单"
    assert isinstance(detail, PortableReply)
    assert cast("TextPart", detail.message.parts[0]).text == "正文:dynamic-2"
    assert detail.additional_stream is not None
    streamed = [message async for message in detail.additional_stream()]
    assert isinstance(streamed[0].parts[0], RemoteImagePart)
    assert sessions.recognizes_response("1", context)
    exited = await sessions.select("0", context)
    assert exited is not None
    assert cast("TextPart", exited.parts[0]).text == "已退出动态选择。"
    assert not sessions.recognizes_response("1", context)
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
        refresh_now=lambda: _refresh_result("完成"),
    )["bilibili.dynamic"]

    result = cast(
        "OutboundMessage",
        await operation("动态", _context("动态")),
    )

    assert "Cookie 已失效" in cast("TextPart", result.parts[0]).text
    assert notifications == ["用户查询动态时发现 B 站登录失效"]


@pytest.mark.asyncio
async def test_portable_bilibili_account_and_push_mode_keep_account_scope() -> None:
    service = _FakeBilibiliService()

    async def notify(_reason: str) -> None:
        return None

    operations = build_portable_bilibili_operations(
        cast("BilibiliService", service),
        PortableQuerySessions(),
        notify_auth_invalid=notify,
        refresh_now=lambda: _refresh_result("完成"),
    )
    context = _context("B站账号")

    accounts = cast(
        "OutboundMessage",
        await operations["bilibili.accounts"]("B站账号", context),
    )
    mode = cast(
        "OutboundMessage",
        await operations["bilibili.private_push_mode"](
            "B站推送模式 示例账号 链接",
            context,
        ),
    )

    assert cast("TextPart", accounts.parts[0]).text == ("账号:example-app:opaque-user")
    assert cast("TextPart", mode.parts[0]).text == ("模式:example-app:示例账号:链接")


async def _refresh_result(message: str) -> str:
    return message


@pytest.mark.asyncio
async def test_portable_bilibili_refresh_uses_shared_monitor_action() -> None:
    service = _FakeBilibiliService()
    calls = 0

    async def notify(_reason: str) -> None:
        return None

    async def refresh() -> str:
        nonlocal calls
        calls += 1
        return "✅ 动态刷新完成。"

    operations = build_portable_bilibili_operations(
        cast("BilibiliService", service),
        PortableQuerySessions(),
        notify_auth_invalid=notify,
        refresh_now=refresh,
    )

    result = cast(
        "OutboundMessage",
        await operations["bilibili.refresh"]("动态刷新", _context("动态刷新")),
    )

    assert cast("TextPart", result.parts[0]).text == "✅ 动态刷新完成。"
    assert calls == 1
