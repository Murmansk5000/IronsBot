import nonebot
from pytest import MonkeyPatch

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.custom_plugins.message_actions import reply_limits


def test_reply_line_limit_api_hook_setup_is_explicit_and_idempotent(
    monkeypatch: MonkeyPatch,
) -> None:
    registered: list[object] = []

    def register_hook(callback: object) -> None:
        registered.append(callback)

    monkeypatch.setattr(
        reply_limits.Bot,
        "on_calling_api",
        register_hook,
    )
    registered_state = False
    monkeypatch.setitem(
        reply_limits._reply_line_limit_api_hook_state,
        "registered",
        registered_state,
    )

    reply_limits.setup_reply_line_limit_api_hook()
    reply_limits.setup_reply_line_limit_api_hook()

    assert registered == [reply_limits._limit_reply_lines_before_send]
