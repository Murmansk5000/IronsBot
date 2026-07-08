import re
from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
    PrivateMessageEvent,
)

if TYPE_CHECKING:
    from collections.abc import Callable

TENCENT_MEETING_NUMBER_DIGITS = 10


class MeetingReplyConfig(Protocol):
    @property
    def number(self) -> str: ...

    @property
    def template(self) -> str: ...

    @property
    def commands(self) -> Iterable[str]: ...


def is_meeting_command_event(
    event: MessageEvent,
    config: MeetingReplyConfig,
    *,
    is_group_allowed: "Callable[[int, int, str], bool]",
    is_private_allowed: "Callable[[int, str], bool]",
    command_matches: "Callable[[str, Iterable[str]], bool]",
) -> bool:
    if isinstance(event, GroupMessageEvent):
        if not is_group_allowed(event.user_id, event.group_id, "meeting"):
            return False
    elif isinstance(event, PrivateMessageEvent):
        if not is_private_allowed(event.user_id, "meeting"):
            return False
    else:
        return False

    return command_matches(event.get_plaintext(), config.commands)


def build_meeting_reply(config: MeetingReplyConfig) -> str | None:
    raw_number = config.number.strip()
    digits = re.sub(r"\D", "", raw_number)
    if not digits:
        return None

    if len(digits) == TENCENT_MEETING_NUMBER_DIGITS:
        meeting_number = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    else:
        meeting_number = raw_number

    meeting_url = f"https://meeting.tencent.com/p/{digits}"
    template = config.template.replace("\\n", "\n")
    return template.format(
        meeting_number=meeting_number,
        meeting_digits=digits,
        meeting_url=meeting_url,
    )
