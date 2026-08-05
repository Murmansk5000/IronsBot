# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ironsbot.plugins.bilibili.command_rules import is_dynamic_select_reply
from tests.helpers.onebot_events import private_message_event


def test_dynamic_selection_accepts_any_numeric_reply() -> None:
    assert is_dynamic_select_reply(private_message_event("11"))
    assert is_dynamic_select_reply(private_message_event("0"))
    assert not is_dynamic_select_reply(private_message_event("第11条"))
