from collections.abc import Iterable

from nonebot.adapters.onebot.v11 import Message, MessageSegment

from ironsbot.shared.messages import text as shared_text

DEFAULT_COMMAND_PREFIXES = shared_text.DEFAULT_COMMAND_PREFIXES
command_text_matches = shared_text.command_text_matches
normalize_command_text = shared_text.normalize_command_text
render_text = shared_text.render_text
strip_command_prefix = shared_text.strip_command_prefix


def build_message(
    text: str | Message | MessageSegment,
    at_user_ids: Iterable[int] = (),
) -> Message:
    message = Message()

    for user_id in dict.fromkeys(at_user_ids):
        message += MessageSegment.at(user_id)
        message += MessageSegment.text(" ")

    if isinstance(text, (Message, MessageSegment)):
        message += text
    else:
        message += MessageSegment.text(render_text(text))

    return message
