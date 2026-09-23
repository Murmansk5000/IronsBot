from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import BinaryImagePart, OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_new_content_commands import (
    build_portable_new_content_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.new_content import (
    NewContentCategory,
    NewContentCategoryState,
    NewContentItem,
    NewContentSnapshot,
    NewContentSnapshotChangedError,
)
from ironsbot.services.seer.query_result import QueryReply

if TYPE_CHECKING:
    from ironsbot.services.seer.resources import SeerQueryResources


class _DataQueries:
    def __init__(self, snapshot: NewContentSnapshot) -> None:
        self.snapshot = snapshot

    def new_content_snapshot(self) -> NewContentSnapshot:
        return self.snapshot


class _Details:
    async def select(
        self,
        _snapshot: NewContentSnapshot,
        item: NewContentItem,
        **_kwargs: object,
    ) -> QueryReply | str:
        if item.category == "pet":
            return QueryReply(text=f"精灵详情:{item.entity_id}")
        return f"成就详情:{item.entity_id}"


class _AutocardMedia:
    async def outbound(self, *_args: object, **_kwargs: object) -> OutboundMessage:
        raise AssertionError


class _MenuRenderer:
    def __init__(self, *, changed: bool = False) -> None:
        self.changed = changed
        self.calls: list[
            tuple[tuple[NewContentCategory, ...], NewContentCategory | None]
        ] = []

    async def __call__(  # noqa: PLR0913
        self,
        snapshot: NewContentSnapshot,
        display_categories: tuple[NewContentCategory, ...],
        focused_category: NewContentCategory | None,
        menu_title: str,
        expanded_categories: frozenset[NewContentCategory],
        auto_expand_max_items: int,
    ) -> bytes:
        del snapshot, expanded_categories, auto_expand_max_items
        assert menu_title == "新增内容"
        self.calls.append((display_categories, focused_category))
        if self.changed:
            raise NewContentSnapshotChangedError
        return b"rendered-menu"


def _snapshot() -> NewContentSnapshot:
    return NewContentSnapshot(
        baseline_established=True,
        config_version="20260911",
        weekly_cycle="2026-09-11",
        items=(
            NewContentItem("pet", 4927, "超级噗纽", 4927, {}),
            NewContentItem(
                "achievement",
                6171016,
                "深海之泪",
                6171016,
                {"point": 10},
            ),
        ),
        category_states=(
            NewContentCategoryState(
                "pet",
                comparison_ready=True,
                reason="comparable",
            ),
            NewContentCategoryState(
                "achievement",
                comparison_ready=True,
                reason="comparable",
            ),
        ),
    )


def _context(text: str = "新增内容") -> MessageInputContext:
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


def _features(*features: str) -> FeatureService:
    return FeatureService(
        group_features={},
        actor_features={_context().message.actor: frozenset(features)},
        superusers=frozenset(),
    )


def _resources(
    snapshot: NewContentSnapshot,
    renderer: _MenuRenderer | None = None,
) -> SeerQueryResources:
    return cast(
        "SeerQueryResources",
        SimpleNamespace(
            data_queries=_DataQueries(snapshot),
            new_content_details=_Details(),
            autocard_media=_AutocardMedia(),
            new_content_menu=renderer or _MenuRenderer(),
        ),
    )


def _text(message: OutboundMessage | None) -> str:
    assert message is not None
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


@pytest.mark.asyncio
async def test_root_menu_replaces_category_session_with_numeric_item_menu() -> None:
    sessions = PortableQuerySessions()
    renderer = _MenuRenderer()
    operations = build_portable_new_content_operations(
        _resources(_snapshot(), renderer),
        sessions,
        _features("seer_data", "seer_pet"),
        preview_max_items=0,
    )
    context = _context()

    root = cast(
        "OutboundMessage",
        await operations["seer.data.new_content"]("新增内容", context),
    )
    category = await sessions.select("1", context)
    detail = await sessions.select("1", context)

    assert root.parts == (BinaryImagePart(b"rendered-menu", "image/png"),)
    assert root.prompt is not None
    assert [choice.label for choice in root.prompt.choices][:2] == [
        "▶ 新增精灵",
        "▶ 新增成就",
    ]
    assert category is not None
    assert category.parts == root.parts
    assert category.prompt is not None
    assert category.prompt.choices[0].label == "超级噗纽"
    assert renderer.calls == [(("pet", "achievement"), None), (("pet",), "pet")]
    assert _text(detail) == "精灵详情:4927"
    assert sessions.recognizes_response("1", context)


@pytest.mark.asyncio
async def test_focused_command_reuses_spec_and_enforces_category_features() -> None:
    sessions = PortableQuerySessions()
    resources = _resources(_snapshot())
    allowed = build_portable_new_content_operations(
        resources,
        sessions,
        _features("seer_data", "seer_pet"),
    )
    denied = build_portable_new_content_operations(
        resources,
        PortableQuerySessions(),
        _features("seer_data"),
    )
    context = _context("新增精灵")

    menu = cast(
        "OutboundMessage",
        await allowed["seer.data.new_pet"]("新增精灵", context),
    )
    denied_result = cast(
        "OutboundMessage",
        await denied["seer.data.new_pet"]("新增精灵", context),
    )

    assert menu.parts == (BinaryImagePart(b"rendered-menu", "image/png"),)
    assert menu.prompt is not None
    assert menu.prompt.choices[0].label == "超级噗纽"
    assert _text(denied_result) == "当前群未开放此新增内容分类。"


@pytest.mark.asyncio
async def test_changed_publication_does_not_install_an_unrendered_menu() -> None:
    sessions = PortableQuerySessions()
    operations = build_portable_new_content_operations(
        _resources(_snapshot(), _MenuRenderer(changed=True)),
        sessions,
        _features("seer_data", "seer_pet"),
    )
    context = _context()
    result = cast(
        "OutboundMessage",
        await operations["seer.data.new_content"]("新增内容", context),
    )
    assert "数据已更新" in _text(result)
    assert not sessions.has_active_session(context)


def test_new_content_specs_are_the_single_operation_inventory() -> None:
    operations = build_portable_new_content_operations(
        _resources(_snapshot()),
        PortableQuerySessions(),
        _features("seer_data", "seer_pet"),
    )

    assert set(operations) == {
        "seer.data.new_content",
        "seer.data.new_achievement",
        "seer.data.new_pet",
        "seer.data.peak_environment_changes",
        "seer.data.new_skin",
        "seer.data.new_skill",
        "seer.data.new_mintmark",
        "seer.data.new_suit",
        "seer.data.new_equip",
        "seer.data.new_mount",
        "seer.data.new_autocard",
        "seer.data.new_autocard_role",
        "seer.data.new_autocard_sanctuary_effect",
    }
