from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

AI_NOTICE_MESSAGE_MAX_CHARS = 300


def build_ai_notice_source_context(event: MessageEvent, prompt: str) -> str:
    lines: list[str] = []
    if isinstance(event, GroupMessageEvent):
        lines.append(f"群：{event.group_id}")
    else:
        lines.append("会话：私聊")

    sender_name = _get_sender_display_name(event)
    user_label = str(event.user_id)
    if sender_name:
        user_label = f"{user_label}（{sender_name}）"
    lines.append(f"用户：{user_label}")

    message_id = getattr(event, "message_id", None)
    if message_id is not None:
        lines.append(f"消息ID：{message_id}")

    text = _truncate_notice_message(prompt.strip() or event.get_plaintext().strip())
    lines.append(f"消息：{text or '（空）'}")
    return "\n".join(lines)


def append_ai_notice_source_context(message: str, source_context: str | None) -> str:
    source = (source_context or "").strip()
    if not source:
        return message
    return f"{message.rstrip()}\n\n触发来源：\n{source}"


def _get_sender_display_name(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    for key in ("card", "nickname"):
        value = ""
        if isinstance(sender, dict):
            value = str(sender.get(key) or "").strip()
        elif sender is not None:
            value = str(getattr(sender, key, "") or "").strip()
        if value:
            return value
    return ""


def _truncate_notice_message(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= AI_NOTICE_MESSAGE_MAX_CHARS:
        return compact
    return compact[:AI_NOTICE_MESSAGE_MAX_CHARS].rstrip() + "..."


__all__ = [
    "append_ai_notice_source_context",
    "build_ai_notice_source_context",
]
