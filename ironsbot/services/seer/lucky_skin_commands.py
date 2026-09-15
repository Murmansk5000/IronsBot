# SPDX-License-Identifier: MIT
"""Command contracts owned by the lucky-skin-window domain."""

from __future__ import annotations

from functools import partial

from ironsbot.core.command_catalog import CommandContract, parsed_command_input_matcher
from ironsbot.core.commands import normalize_command_text
from ironsbot.core.semantic_requests import ActionDefinition

LUCKY_SKIN_QUERY_COMMANDS = ("幸运橱窗", "橱窗")
LUCKY_SKIN_WATCH_LIST_COMMANDS = (
    "关注橱窗",
    "订阅橱窗",
    "橱窗关注",
    "橱窗订阅",
)
LUCKY_SKIN_WATCH_REMOVE_COMMANDS = (
    "取消关注橱窗",
    "取消订阅橱窗",
    "取消橱窗关注",
    "取消橱窗订阅",
    "退订橱窗",
    "橱窗退订",
)
LUCKY_SKIN_WATCH_CLEAR_COMMANDS = (
    "清空关注橱窗",
    "清空订阅橱窗",
    "清空橱窗关注",
    "清空橱窗订阅",
)
LUCKY_SKIN_WATCH_RESET_COMMANDS = (
    "重置关注橱窗",
    "重置订阅橱窗",
    "重置橱窗关注",
    "重置橱窗订阅",
)

LUCKY_SKIN_QUERY_ACTION = ActionDefinition("seer.lucky_skin_window.query", "幸运橱窗")
LUCKY_SKIN_WATCH_LIST_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.list",
    "查看橱窗关注",
)
LUCKY_SKIN_WATCH_ADD_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.add",
    "新增橱窗关注",
)
LUCKY_SKIN_WATCH_REMOVE_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.remove",
    "取消橱窗关注",
)
LUCKY_SKIN_WATCH_CLEAR_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.clear",
    "清空橱窗关注",
)
LUCKY_SKIN_WATCH_RESET_ACTION = ActionDefinition(
    "seer.lucky_skin_window.watch.reset",
    "重置橱窗关注",
)


def is_lucky_skin_query(text: str) -> bool:
    return parse_lucky_skin_query(text) is not None


def parse_lucky_skin_query(text: str) -> str | None:
    text = normalize_command_text(text)
    prefixes = {
        *LUCKY_SKIN_QUERY_COMMANDS,
        *LUCKY_SKIN_WATCH_LIST_COMMANDS,
        *LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
        *LUCKY_SKIN_WATCH_CLEAR_COMMANDS,
        *LUCKY_SKIN_WATCH_RESET_COMMANDS,
    }
    for command in sorted(prefixes, key=len, reverse=True):
        if text.startswith(command):
            return (
                text[len(command):].strip()
                if command in LUCKY_SKIN_QUERY_COMMANDS else None
            )
    return None


def is_lucky_skin_watch_exact(text: str, *, commands: tuple[str, ...]) -> bool:
    return text.strip() in commands


def parse_lucky_skin_watch_target(
    text: str, *, commands: tuple[str, ...]
) -> str | None:
    text = text.strip()
    for command in sorted(commands, key=len, reverse=True):
        if text.startswith(command):
            return text[len(command) :].strip() or None
    return None


def lucky_skin_window_command_contracts() -> tuple[CommandContract, ...]:
    """Describe all direct lucky-skin-window commands."""

    return (
        CommandContract(
            id=LUCKY_SKIN_QUERY_ACTION.id,
            plugin_id="lucky_skin_window",
            section="幸运橱窗",
            examples=("橱窗",),
            routing_matcher=lambda text, _context: is_lucky_skin_query(text),
            description="查看每日橱窗；超级管理员可附加米米号、账号别名或 @成员查询",
            features_any=("lucky_skin_window",),
            show_in_poke=True,
        ),
        CommandContract(
            id=LUCKY_SKIN_WATCH_LIST_ACTION.id,
            plugin_id="lucky_skin_window",
            section="橱窗关注",
            examples=LUCKY_SKIN_WATCH_LIST_COMMANDS,
            routing_matcher=lambda text, _context: is_lucky_skin_watch_exact(
                text, commands=LUCKY_SKIN_WATCH_LIST_COMMANDS
            ),
            description="查看当前账号的幸运橱窗关注列表",
            features_any=("lucky_skin_window",),
            show_in_poke=True,
        ),
        CommandContract(
            id=LUCKY_SKIN_WATCH_ADD_ACTION.id,
            plugin_id="lucky_skin_window",
            section="橱窗关注",
            examples=("关注橱窗1400538", "订阅橱窗1400538", "橱窗订阅名称"),
            routing_matcher=parsed_command_input_matcher(
                partial(
                    parse_lucky_skin_watch_target,
                    commands=LUCKY_SKIN_WATCH_LIST_COMMANDS,
                )
            ),
            description="按皮肤 ID、资源 ID 或名称新增橱窗关注",
            features_any=("lucky_skin_window",),
        ),
        CommandContract(
            id=LUCKY_SKIN_WATCH_REMOVE_ACTION.id,
            plugin_id="lucky_skin_window",
            section="橱窗关注",
            examples=("取消关注橱窗1400538", "退订橱窗1400538", "橱窗退订名称"),
            routing_matcher=parsed_command_input_matcher(
                partial(
                    parse_lucky_skin_watch_target,
                    commands=LUCKY_SKIN_WATCH_REMOVE_COMMANDS,
                )
            ),
            description="取消指定皮肤的橱窗关注",
            features_any=("lucky_skin_window",),
        ),
        CommandContract(
            id=LUCKY_SKIN_WATCH_CLEAR_ACTION.id,
            plugin_id="lucky_skin_window",
            section="橱窗关注",
            examples=LUCKY_SKIN_WATCH_CLEAR_COMMANDS,
            routing_matcher=lambda text, _context: is_lucky_skin_watch_exact(
                text, commands=LUCKY_SKIN_WATCH_CLEAR_COMMANDS
            ),
            description="清空当前账号的幸运橱窗关注列表",
            features_any=("lucky_skin_window",),
        ),
        CommandContract(
            id=LUCKY_SKIN_WATCH_RESET_ACTION.id,
            plugin_id="lucky_skin_window",
            section="橱窗关注",
            examples=LUCKY_SKIN_WATCH_RESET_COMMANDS,
            routing_matcher=lambda text, _context: is_lucky_skin_watch_exact(
                text, commands=LUCKY_SKIN_WATCH_RESET_COMMANDS
            ),
            description="恢复 TOML 中配置的初始幸运橱窗关注列表",
            features_any=("lucky_skin_window",),
        ),
    )
