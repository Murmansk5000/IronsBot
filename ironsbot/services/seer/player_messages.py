# SPDX-License-Identifier: GPL-3.0-or-later
"""Shared user-facing messages for player query entry points."""

from __future__ import annotations


def unbound_player_shortcut_message() -> str:
    """Explain how an unbound user can use player shortcut commands."""

    return (
        "尚未绑定米米号，发送“绑定米米号123456”绑定后，即可使用快捷指令。\n"
        "查询未绑定的米米号时，需要在查询指令后加上米米号。"
    )
