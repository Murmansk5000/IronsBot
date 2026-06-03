from collections.abc import Iterable

from nonebot.adapters.onebot.v11 import Message, MessageSegment


def normalize_command_text(text: str) -> str:
    return "".join(text.split())


def command_text_matches(text: str, commands: Iterable[str]) -> bool:
    normalized = normalize_command_text(text)
    return normalized in {
        normalize_command_text(command)
        for command in commands
    }


def render_text(text: str) -> str:
    return text.replace("\\n", "\n")


def build_message(text: str | Message, at_user_ids: Iterable[int] = ()) -> Message:
    message = Message()

    for user_id in dict.fromkeys(at_user_ids):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(" ")

    if isinstance(text, Message):
        message += text
    else:
        message += MessageSegment.text(render_text(text))

    return message
