# SPDX-License-Identifier: MIT
from __future__ import annotations

from ironsbot.core.commands import normalize_command_text, strip_command_prefix

CURRENT_ACTIVITY_COMMANDS = ("当前活动", "活动列表", "活动时间")
NEW_ACTIVITY_COMMANDS = ("新增活动",)
SOON_ENDING_ACTIVITY_COMMANDS = (
    "快结束活动",
    "即将结束活动",
    "即将结束",
    "本周结束活动",
    "本周活动",
    "活动快结束",
)

NORMALIZED_CURRENT_ACTIVITY_COMMANDS = {
    normalize_command_text(command)
    for command in CURRENT_ACTIVITY_COMMANDS
}
NORMALIZED_NEW_ACTIVITY_COMMANDS = {
    normalize_command_text(command)
    for command in NEW_ACTIVITY_COMMANDS
}
NORMALIZED_SOON_ENDING_ACTIVITY_COMMANDS = {
    normalize_command_text(command)
    for command in SOON_ENDING_ACTIVITY_COMMANDS
}


def is_current_seer_activity_text(text: str) -> bool:
    command = strip_command_prefix(text)
    if command is None:
        return False

    normalized = normalize_command_text(command)
    return normalized in NORMALIZED_CURRENT_ACTIVITY_COMMANDS


def is_soon_ending_seer_activity_text(text: str) -> bool:
    text_value = text.strip()
    command = strip_command_prefix(text_value) or text_value

    normalized = normalize_command_text(command)
    return normalized in NORMALIZED_SOON_ENDING_ACTIVITY_COMMANDS


def is_new_seer_activity_text(text: str) -> bool:
    text_value = text.strip()
    command = strip_command_prefix(text_value) or text_value

    normalized = normalize_command_text(command)
    return normalized in NORMALIZED_NEW_ACTIVITY_COMMANDS
