from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest

from ironsbot.core.command_catalog import CommandCatalog, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import HelpEntry, PluginContribution
from ironsbot.integrations.onebot.context import command_context
from ironsbot.services.help_menu import (
    HelpMenuEntry,
    build_portable_help_operation,
    format_plugin_detail,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from tests.helpers.onebot_events import private_message_event

if TYPE_CHECKING:
    from ironsbot.core.outbound import OutboundMessage, TextPart


def test_detail_labels_automatic_behaviour_without_claiming_no_commands() -> None:
    automatic = CommandContract(
        id="example.automatic",
        plugin_id="example",
        section="Intent",
        examples=("keyword",),
        description="Respond when the keyword is recognized",
        interaction="automatic",
    )
    commands = SimpleNamespace(
        available_for_context=lambda *_args, **_kwargs: (automatic,)
    )
    event = private_message_event(user_id=1)
    entry = HelpMenuEntry(
        key="example",
        name="Example",
        description="Example plugin",
        group="other",
        order=1,
        notes=(),
    )

    detail = format_plugin_detail(
        entry,
        command_context(event),
        cast("Any", object()),
        cast("Any", commands),
        ignored_plugins=(),
    )

    assert "自动响应" in detail
    assert "暂无可直接输入的命令" not in detail
    assert "keyword" in detail


@pytest.mark.asyncio
async def test_portable_help_uses_shared_directory_and_keeps_menu_open() -> None:
    actor = ActorRef(Platform.QQ_OFFICIAL, "openid", account_id="app")
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        actor.id,
        account_id="app",
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=conversation,
            message_id="message",
            text="帮助",
        ),
        mentions_bot=False,
    )
    definitions = (
        PluginContribution(
            id="help",
            help=HelpEntry("帮助", "查看功能", "core", 10),
            commands=(
                CommandContract(
                    id="help",
                    plugin_id="help",
                    section="查看",
                    examples=("帮助",),
                    description="查看当前可用功能",
                    features_any=("help",),
                ),
            ),
        ),
        PluginContribution(
            id="about",
            help=HelpEntry("关于", "项目信息", "core", 20),
            commands=(
                CommandContract(
                    id="about",
                    plugin_id="about",
                    section="查看",
                    examples=("关于",),
                    description="查看项目信息",
                    features_any=("about",),
                ),
            ),
        ),
    )
    catalog = CommandCatalog()
    catalog.load(definitions, known_features={"help", "about"})
    features = FeatureService(
        {},
        {},
        frozenset(),
        account_default_features={
            (Platform.QQ_OFFICIAL, "app"): frozenset({"help", "about"})
        },
    )
    sessions = PortableQuerySessions()
    operation = build_portable_help_operation(
        definitions,
        catalog,
        features,
        sessions,
        command_ids=frozenset({"help", "about"}),
    )

    menu = cast("OutboundMessage", await operation("帮助", context))
    assert "可用功能" in cast("TextPart", menu.parts[0]).text
    assert "关于" in cast("TextPart", menu.parts[0]).text

    detail = cast("OutboundMessage", await sessions.select("2", context))
    assert "📖 关于" in cast("TextPart", detail.parts[0]).text
    assert sessions.recognizes_response("1", context)

    exited = cast("OutboundMessage", await sessions.select("0", context))
    assert cast("TextPart", exited.parts[0]).text == "✅ 已退出帮助。"
