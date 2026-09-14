from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from ironsbot.core.command_catalog import CommandContract
from ironsbot.plugins.onebot.help.menu import HelpMenuEntry, format_plugin_detail
from tests.helpers.onebot_events import private_message_event


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
        cast("Any", event),
        cast("Any", object()),
        cast("Any", commands),
        ignored_plugins=(),
    )

    assert "自动响应" in detail
    assert "暂无可直接输入的命令" not in detail
    assert "keyword" in detail
