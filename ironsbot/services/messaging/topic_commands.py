# SPDX-License-Identifier: MIT
"""One parser and command handler shared by both messaging adapters."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from ironsbot.core.authorization import GROUP_MANAGER_ROLES
from ironsbot.core.command_catalog import CommandAccess, CommandContract
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.services.messaging.topics import TopicPublication

if TYPE_CHECKING:

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.services.messaging.topics import PushTopicService
    from ironsbot.services.portable_reply import PortableOperation


def reference_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True, slots=True)
class TopicCommand:
    action: str
    arguments: tuple[str, ...]


_COMMANDS = (
    ("list", "推送列表", "查看推送主题"),
    ("create", "推送新建 公告 群公告", "新建推送主题"),
    ("enable", "推送启用 公告", "启用推送主题"),
    ("disable", "推送停用 公告", "停用主题并取消调度"),
    ("delete", "推送删除 公告", "删除非程序注册的主题"),
    ("subscribers", "推送订阅者 公告", "查看主题订阅者数量"),
    ("broadcast", "推送 公告 本次公告内容", "向主题订阅者广播"),
    ("direct", "推送直发 公告 群:群别名 内容", "向明确指定的已授权目标发送"),
    ("subscribe", "订阅公告", "订阅主题；群聊需群主或管理员"),
    ("unsubscribe", "退订公告", "退订当前会话的主题"),
    ("mine", "我的订阅", "查看当前会话的主题订阅"),
)
_ADMIN_ACTIONS = frozenset(
    {"create", "enable", "disable", "delete", "subscribers", "broadcast", "direct"}
)
_PREFIXES = {
    "推送新建": "create",
    "推送启用": "enable",
    "推送停用": "disable",
    "推送删除": "delete",
    "推送订阅者": "subscribers",
    "推送直发": "direct",
    "推送": "broadcast",
}


def parse_topic_command(
    text: str, known_keys: set[str] | None = None
) -> TopicCommand | None:
    value = text.strip().lstrip("/").strip()
    if value in {"推送列表", "主题列表"}:
        return TopicCommand("list", ())
    if value == "我的订阅":
        return TopicCommand("mine", ())
    for prefix, action in _PREFIXES.items():
        if value == prefix or value.startswith(prefix + " "):
            return TopicCommand(
                action,
                tuple(
                    value[len(prefix) :].split(
                        maxsplit=2 if action == "direct" else 1,
                    )
                ),
            )
    for prefix, action in (("订阅", "subscribe"), ("退订", "unsubscribe")):
        explicit = prefix + "主题 "
        if value.startswith(explicit):
            return TopicCommand(action, (value[len(explicit) :].strip(),))
        key = value.removeprefix(prefix).strip()
        if value.startswith(prefix) and key in (known_keys or set()):
            return TopicCommand(action, (key,))
    return None


def _matches(
    action: str, service: PushTopicService | None, text: str, _context: object
) -> bool:
    parsed = parse_topic_command(text, service.known_keys if service else None)
    return parsed is not None and parsed.action == action


def topic_command_contracts(
    service: PushTopicService | None = None,
) -> tuple[CommandContract, ...]:
    return tuple(
        CommandContract(
            id=f"messaging.topic.{action}",
            plugin_id="messaging",
            section="主题推送",
            examples=(example,),
            description=description,
            features_any=("push_topics",),
            access=(CommandAccess(audience="superuser"),)
            if action in _ADMIN_ACTIONS
            else (CommandAccess("group", "group_manager"), CommandAccess("private"))
            if action in {"subscribe", "unsubscribe"}
            else (CommandAccess(),),
            routing_matcher=partial(_matches, action, service),
        )
        for action, example, description in _COMMANDS
    )


def build_topic_operations(
    service: PushTopicService,
) -> dict[str, PortableOperation]:
    async def execute(text: str, context: MessageInputContext) -> OutboundMessage:
        command = parse_topic_command(text, service.known_keys)
        if command is None:
            msg = "topic catalog accepted an invalid command"
            raise ValueError(msg)
        message = context.message
        if not service.features.is_feature_allowed(
            message.actor,
            message.conversation,
            "push_topics",
        ):
            return OutboundMessage((TextPart("当前会话未启用主题推送。"),))
        is_admin = service.features.is_actor_superuser(message.actor)
        if command.action in _ADMIN_ACTIONS and not is_admin:
            return OutboundMessage((TextPart("此操作仅限超级管理员。"),))
        if command.action in {"subscribe", "unsubscribe"} and (
            message.conversation.kind == "group"
            and not is_admin
            and message.group_role not in GROUP_MANAGER_ROLES
        ):
            return OutboundMessage((TextPart("仅群主和管理员可以修改本群订阅。"),))
        try:
            result = await _execute(service, command, context)
        except ValueError as exc:
            result = str(exc)
        return OutboundMessage((TextPart(result),))

    return {f"messaging.topic.{action}": execute for action, _, _ in _COMMANDS}


async def _execute(  # noqa: C901, PLR0911 - explicit topic command dispatch
    service: PushTopicService, command: TopicCommand, context: MessageInputContext
) -> str:
    action, args = command.action, command.arguments
    target = context.message.conversation
    if action == "list":
        topics = await asyncio.to_thread(service.store.topics)
        return (
            "推送主题：\n"
            + "\n".join(
                f"{topic.key}：{topic.name}（{'启用' if topic.enabled else '停用'}）"
                for topic in topics
            )
            if topics
            else "当前没有推送主题。"
        )
    if action == "mine":
        options = await asyncio.to_thread(service.subscription_options, target)
        return (
            "\n".join(
                f"{'❌' if option.unsubscribed else '✅'} {option.label}"
                for option in options
            )
            or "当前没有主题订阅。"
        )
    required = (
        3 if action == "direct" else 2 if action in {"create", "broadcast"} else 1
    )
    if len(args) != required:
        raise ValueError("参数不完整，请查看帮助中的主题推送示例。")
    key = args[0]
    if action == "create":
        await asyncio.to_thread(service.create, key, args[1])
        return "已创建推送主题。"
    if action in {"subscribe", "unsubscribe"}:
        await asyncio.to_thread(
            service.subscribe, key, target, enabled=action == "subscribe"
        )
        return "已订阅。" if action == "subscribe" else "已退订。"
    if action == "subscribers":
        await asyncio.to_thread(service.topic, key)
        subscribers = await asyncio.to_thread(service.store.subscribers, key)
        active_subscribers = await asyncio.to_thread(
            service.subscriptions.filter_subscribed_conversations,
            list(subscribers),
            f"push_topic:{key}",
        )
        return f"当前有效订阅会话：{len(active_subscribers)}。" + (
            "\n"
            + "\n".join(
                f"{item.platform.value} / {item.kind} / {reference_digest(item.id)}"
                for item in active_subscribers
            )
            if active_subscribers
            else ""
        )
    if action in {"enable", "disable"}:
        await service.set_enabled(key, enabled=action == "enable")
        return "已启用主题。" if action == "enable" else "已停用主题。"
    if action == "delete":
        await service.delete(key)
        return "已删除主题。"
    destinations = None
    content = args[1]
    if action == "direct":
        if service.resolve_target is None:
            raise ValueError("当前未配置直发目标解析。")
        destinations = service.resolve_target(args[1], target)
        if not destinations:
            raise ValueError("没有找到当前机器人可用的明确目标。")
        content = args[2]
    counts = await service.publish(
        key,
        TopicPublication(
            OutboundMessage((TextPart(content),)),
            dedup_key=f"command:{target.platform.value}:{target.account_id}:{target.id}:"
            f"{context.message.message_id}",
        ),
        targets=destinations,
    )
    return "投递结果：" + (
        "、".join(f"{name}={count}" for name, count in counts.items())
        or "无符合条件的目标"
    )
