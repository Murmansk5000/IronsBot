from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_autocard_commands import (
    build_portable_autocard_operations,
)
from ironsbot.services.portable_countermark_commands import (
    build_portable_countermark_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.autocard import (
    AutocardEntry,
    AutocardPromptValue,
    AutocardSearchResult,
)
from ironsbot.services.seer.autocard_sanctuary import (
    AutocardSanctuaryRow,
    AutocardSanctuaryService,
)
from ironsbot.services.seer.data import DataUnavailableError
from ironsbot.services.seer.errors import DATABASE_UNAVAILABLE_MESSAGE

if TYPE_CHECKING:
    from ironsbot.services.portable_reply import PortableReply
    from ironsbot.services.seer.autocard import AutocardService
    from ironsbot.services.seer.autocard_media import AutocardMediaService
    from ironsbot.services.seer.countermark_stat_rank import (
        CountermarkStatRankService,
    )
    from ironsbot.services.seer.countermark_stat_rank_models import (
        CountermarkStatRankCommand,
    )


class _AutocardService:
    def search(self, text: str) -> AutocardSearchResult:
        if text == "群星牌唯一":
            return AutocardSearchResult(entry=_entry(1, "唯一"))
        return AutocardSearchResult(
            prompt_values=(
                AutocardPromptValue("card", 1),
                AutocardPromptValue("card", 2),
            ),
            prompt_text="群星牌候选菜单",
        )

    def select(self, value: AutocardPromptValue) -> AutocardEntry:
        return _entry(value.item_id, f"卡牌{value.item_id}")


class _Media:
    async def outbound(
        self,
        entry: AutocardEntry,
        *,
        include_additional_images: bool = True,
    ) -> OutboundMessage:
        del include_additional_images
        return entry.to_outbound()


class _ImageMedia(_Media):
    async def outbound(
        self,
        entry: AutocardEntry,
        *,
        include_additional_images: bool = True,
    ) -> OutboundMessage:
        del include_additional_images
        return entry.to_outbound(image_contents=(b"image",))


class _SanctuaryRows:
    def load(self) -> tuple[AutocardSanctuaryRow, ...]:
        return (
            AutocardSanctuaryRow(
                100,
                10,
                "元素圣域",
                "基础效果",
                0,
                0,
                "元素圣域",
                70,
                "雷伊",
            ),
            AutocardSanctuaryRow(
                101,
                10,
                "雷霆祝印",
                "祝印效果",
                1,
                1,
                "元素圣域",
                70,
                "雷伊",
            ),
        )


class _CountermarkRank:
    def __init__(self) -> None:
        self.stat_title = ""

    def query(self, command: CountermarkStatRankCommand) -> str:
        assert command.stat is not None
        self.stat_title = command.stat.title
        return "刻印榜结果"


class _UnavailableCountermarkRank(_CountermarkRank):
    def query(self, command: CountermarkStatRankCommand) -> str:
        del command
        raise DataUnavailableError


def _entry(item_id: int, name: str) -> AutocardEntry:
    return AutocardEntry("card", item_id, name, f"卡牌详情:{item_id}", "")


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


def _text(message: OutboundMessage | None) -> str:
    assert message is not None
    return "".join(
        part.text for part in message.parts if isinstance(part, TextPart)
    )


@pytest.mark.asyncio
async def test_autocard_query_supports_direct_and_reusable_menu_results() -> None:
    sessions = PortableQuerySessions()
    operations = build_portable_autocard_operations(
        cast("AutocardService", _AutocardService()),
        cast("AutocardMediaService", _Media()),
        AutocardSanctuaryService(_SanctuaryRows()),
        sessions,
    )
    context = _context("群星牌测试")

    direct = cast(
        "OutboundMessage",
        await operations["seer.autocard.query"]("群星牌唯一", context),
    )
    menu = cast(
        "OutboundMessage",
        await operations["seer.autocard.query"]("群星牌测试", context),
    )
    selected = await sessions.select("2", context)

    assert _text(direct) == "卡牌详情:1"
    assert _text(menu) == "群星牌候选菜单"
    assert _text(selected) == "卡牌详情:2"
    assert sessions.recognizes_response("1", context)


@pytest.mark.asyncio
async def test_autocard_image_reply_declares_text_fallback() -> None:
    operations = build_portable_autocard_operations(
        cast("AutocardService", _AutocardService()),
        cast("AutocardMediaService", _ImageMedia()),
        AutocardSanctuaryService(_SanctuaryRows()),
        PortableQuerySessions(),
    )

    result = cast(
        "PortableReply",
        await operations["seer.autocard.query"](
            "群星牌唯一",
            _context("群星牌唯一"),
        ),
    )

    assert isinstance(result.message.parts[0], BinaryImagePart)
    assert result.fallback_message is not None
    assert _text(result.fallback_message) == "卡牌详情:1"


@pytest.mark.asyncio
async def test_sanctuary_selection_replaces_root_with_effect_menu() -> None:
    sessions = PortableQuerySessions()
    operations = build_portable_autocard_operations(
        cast("AutocardService", _AutocardService()),
        cast("AutocardMediaService", _Media()),
        AutocardSanctuaryService(_SanctuaryRows()),
        sessions,
    )
    context = _context("圣域")

    root = cast(
        "OutboundMessage",
        await operations["seer.autocard.sanctuary"]("圣域", context),
    )
    overview = await sessions.select("1", context)
    effect = await sessions.select("2", context)

    assert "元素圣域" in _text(root)
    assert "关联精灵王：雷伊" in _text(overview)
    assert "雷霆祝印" in _text(effect)
    assert "祝印效果" in _text(effect)


@pytest.mark.asyncio
async def test_countermark_rank_reuses_shared_parser_and_service() -> None:
    service = _CountermarkRank()
    operation = build_portable_countermark_operations(
        cast("CountermarkStatRankService", service)
    )["seer.mintmark.rank"]

    result = cast(
        "OutboundMessage",
        await operation("六角双攻榜", _context("六角双攻榜")),
    )

    assert _text(result) == "刻印榜结果"
    assert service.stat_title == "双攻"


@pytest.mark.asyncio
async def test_countermark_rank_maps_unavailable_data_for_every_platform() -> None:
    operation = build_portable_countermark_operations(
        cast("CountermarkStatRankService", _UnavailableCountermarkRank())
    )["seer.mintmark.rank"]

    result = cast(
        "OutboundMessage",
        await operation("六角双攻榜", _context("六角双攻榜")),
    )

    assert _text(result) == DATABASE_UNAVAILABLE_MESSAGE
