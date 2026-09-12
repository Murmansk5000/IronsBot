from __future__ import annotations

import re

from ironsbot.core.command_catalog import (
    CommandContract,
    normalized_command_input_matcher,
)

TENCENT_MEETING_NUMBER_DIGITS = 10


def build_meeting_reply(number: str, template: str) -> str | None:
    raw_number = number.strip()
    digits = re.sub(r"\D", "", raw_number)
    if not digits:
        return None

    if len(digits) == TENCENT_MEETING_NUMBER_DIGITS:
        meeting_number = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    else:
        meeting_number = raw_number

    meeting_url = f"https://meeting.tencent.com/p/{digits}"
    return template.replace("\\n", "\n").format(
        meeting_number=meeting_number,
        meeting_digits=digits,
        meeting_url=meeting_url,
    )


def meeting_command_contracts(
    commands: tuple[str, ...],
) -> tuple[CommandContract, ...]:
    """Describe configured meeting commands for the shared command catalog."""

    return (
        CommandContract(
            id="meeting",
            plugin_id="meeting",
            section="查询",
            examples=commands,
            routing_matcher=normalized_command_input_matcher(commands),
            description="获取配置的腾讯会议信息",
            features_any=("meeting",),
            show_in_poke=True,
        ),
    )
