from importlib import import_module
from typing import get_type_hints

import nonebot
import pytest
from pytest import MonkeyPatch


def _ensure_nonebot_initialized() -> None:
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()


@pytest.mark.parametrize(
    ("module_name", "handler_names"),
    [
        (
            "ironsbot.plugins.seer.query.commands.player_detail_conversation",
            ["handle_player_detail_reply"],
        ),
        (
            "ironsbot.plugins.messaging.push_subscription_handlers",
            ["handle_push_subscription_menu", "handle_push_subscription_select"],
        ),
        (
            "ironsbot.plugins.messaging.push_time_handlers",
            ["handle_push_time_menu", "handle_push_time_select"],
        ),
    ],
)
def test_prompt_handler_annotations_resolve_at_runtime(
    monkeypatch: MonkeyPatch,
    module_name: str,
    handler_names: list[str],
) -> None:
    monkeypatch.setenv("APP_CONFIG_PATH", "config.example.toml")
    _ensure_nonebot_initialized()

    module = import_module(module_name)

    for handler_name in handler_names:
        hints = get_type_hints(getattr(module, handler_name))

        assert {"matcher", "event", "state"} <= set(hints)
