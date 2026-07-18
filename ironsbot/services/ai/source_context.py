from typing import TYPE_CHECKING

from nonebot.adapters.onebot.v11 import GroupMessageEvent, MessageEvent

from ironsbot.services.ai.resources import AiResources

if TYPE_CHECKING:
    from nonebot.adapters.onebot.v11 import Bot

AI_NOTICE_MESSAGE_MAX_CHARS = 300


async def build_notice_source(
    event: MessageEvent,
    prompt: str,
    resources: AiResources,
    *,
    bot: "Bot | None" = None,
) -> str:
    lines: list[str] = []
    if isinstance(event, GroupMessageEvent):
        group_label = await _group_display_label(event, bot, resources)
        lines.append(f"群：{group_label}")
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


async def _group_display_label(
    event: GroupMessageEvent, bot: "Bot | None", resources: AiResources
) -> str:
    group_id = int(event.group_id)
    group_name = await _fetch_group_name(bot, group_id)
    if group_name:
        return f"{group_name}（{group_id}）"

    group_alias = _configured_group_alias(group_id, resources)
    if group_alias:
        return f"{group_alias}（{group_id}）"

    return str(group_id)


async def _fetch_group_name(bot: "Bot | None", group_id: int) -> str:
    if bot is None:
        return ""

    try:
        group_info = await bot.get_group_info(group_id=group_id, no_cache=False)
    except Exception:  # noqa: BLE001
        return ""

    if isinstance(group_info, dict):
        return str(group_info.get("group_name") or "").strip()
    return str(getattr(group_info, "group_name", "") or "").strip()


def _configured_group_alias(group_id: int, resources: AiResources) -> str:
    for alias, alias_group_id in resources.group_aliases.items():
        if int(alias_group_id) == group_id:
            return alias
    return ""


def _truncate_notice_message(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= AI_NOTICE_MESSAGE_MAX_CHARS:
        return compact
    return compact[:AI_NOTICE_MESSAGE_MAX_CHARS].rstrip() + "..."


__all__ = [
    "append_ai_notice_source_context",
    "build_notice_source",
]
