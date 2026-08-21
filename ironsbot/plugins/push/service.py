# SPDX-License-Identifier: MIT
import time
from collections.abc import Sequence
from typing import TypeAlias

from nonebot import logger
from nonebot_plugin_saa import MessageFactory, PlatformTarget, Text

from .config import plugin_config
from .models import (
    ContentProvider,
    PushRecord,
    Schedule,
    SendReport,
    Subscription,
    Topic,
    target_key,
)
from .scheduler import setup_topic_schedule
from .storage import PushStorage

#: 持久化层实例（懒初始化引擎，首次读写时建表）
storage = PushStorage(plugin_config.push_data_dir / "push.db")

#: 代码注册的静态主题（命令层据此区分静态主题与 DB 动态创建的主题）
_registered_topics: dict[str, Topic] = {}

Content: TypeAlias = MessageFactory | str


def _serialize_target(target: PlatformTarget) -> str:
    return target.model_dump_json()


def _deserialize_target(source: str) -> PlatformTarget:
    return PlatformTarget.deserialize(source)


def _normalize_content(content: Content) -> MessageFactory:
    if isinstance(content, MessageFactory):
        return content
    return MessageFactory(Text(content))


def _content_preview(msg: MessageFactory, limit: int = 50) -> str:
    parts: list[str] = []
    for seg in msg:
        text = seg.get("text")
        parts.append(str(text) if text else f"[{type(seg).__name__}]")
    preview = "".join(parts).replace("\n", " ")
    return preview[:limit] if len(preview) > limit else preview


def register_topic(  # noqa: PLR0913
    topic_id: str,
    *,
    name: str,
    description: str = "",
    allow_subscribe: bool = True,
    enabled: bool = True,
    schedule: Schedule | None = None,
    provider: ContentProvider | None = None,
) -> None:
    """注册推送主题，供其他插件在模块级调用（幂等）。

    Args:
        topic_id: 主题唯一 ID（建议小写蛇形命名，如 ``"db_sync_status"``）
        name: 主题显示名称（展示给用户，如 ``"公告"``）
        description: 主题描述，展示在「主题列表」中
        allow_subscribe: 是否允许普通用户自助订阅
        enabled: 是否启用；停用后订阅者不再接收推送
        schedule: 定时调度配置；需与 provider 同时提供才会注册定时任务
        provider: 定时内容提供器，返回 ``None`` 表示本次内容无变化、不推送

    已存在的主题会保留 DB 中的 enabled/allow_subscribe 状态，仅更新名称与描述，
    避免代码重启重置停用状态。
    """
    topic = Topic(
        id=topic_id,
        name=name,
        description=description,
        allow_subscribe=allow_subscribe,
        enabled=enabled,
        created_at=time.time(),
    )
    _registered_topics[topic_id] = topic
    storage.upsert_topic(topic)

    if schedule is not None and provider is not None:
        setup_topic_schedule(topic_id, schedule, provider)

    logger.debug(f"已注册推送主题 '{topic_id}'")


def is_registered_static_topic(topic_id: str) -> bool:
    """判断主题是否为代码注册的静态主题。

    静态主题由其他插件在模块级调用 register_topic 注册，只能停用、
    不能通过「推送删除」删除（删除后重启会重新注册）。

    Args:
        topic_id: 主题 ID

    Returns:
        是否为代码注册的静态主题
    """
    return topic_id in _registered_topics


async def create_topic(topic_id: str, *, name: str, description: str = "") -> bool:
    """由管理命令创建 DB 动态主题（不注册定时任务）。

    Args:
        topic_id: 主题唯一 ID
        name: 主题显示名称
        description: 主题描述

    Returns:
        创建成功返回 True；主题已存在返回 False
    """
    if storage.get_topic(topic_id) is not None:
        return False
    storage.upsert_topic(
        Topic(
            id=topic_id,
            name=name,
            description=description,
            created_at=time.time(),
        )
    )
    return True


async def delete_topic(topic_id: str) -> bool:
    """删除主题及其全部订阅、推送历史（级联删除）。

    Args:
        topic_id: 主题 ID

    Returns:
        主题存在并删除成功返回 True；主题不存在返回 False
    """
    return storage.delete_topic(topic_id)


async def update_topic(
    topic_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    allow_subscribe: bool | None = None,
    enabled: bool | None = None,
) -> bool:
    """更新主题的可变字段；未提供的字段保持不变。

    Args:
        topic_id: 主题 ID
        name: 新的显示名称
        description: 新的描述
        allow_subscribe: 是否允许自助订阅
        enabled: 是否启用

    Returns:
        主题存在并更新成功返回 True；主题不存在返回 False
    """
    return storage.update_topic(
        topic_id,
        name=name,
        description=description,
        allow_subscribe=allow_subscribe,
        enabled=enabled,
    )


async def get_topic(topic_id: str) -> Topic | None:
    """按 ID 获取主题。

    Args:
        topic_id: 主题 ID

    Returns:
        主题对象；不存在时返回 None
    """
    return storage.get_topic(topic_id)


async def list_topics() -> list[Topic]:
    """列出全部主题（按 ID 排序）。

    Returns:
        全部主题列表
    """
    return storage.list_topics()


async def subscribe(topic_id: str, target: PlatformTarget) -> bool:
    """订阅主题（当前会话目标）。

    主题不存在、未启用或不允许自助订阅时返回 False。

    Args:
        topic_id: 主题 ID
        target: 订阅目标（如 ``TargetQQGroup`` / ``TargetQQPrivate``）

    Returns:
        订阅成功返回 True；主题不可订阅或已订阅过返回 False
    """
    topic = storage.get_topic(topic_id)
    if topic is None or not topic.enabled or not topic.allow_subscribe:
        return False
    return storage.add_subscription(
        Subscription(
            topic_id=topic_id,
            target=_serialize_target(target),
            target_type=type(target).__name__,
            target_key=target_key(target),
            subscribed_at=time.time(),
        )
    )


async def unsubscribe(topic_id: str, target: PlatformTarget) -> bool:
    """退订主题。

    Args:
        topic_id: 主题 ID
        target: 退订目标

    Returns:
        退订成功返回 True；未订阅过返回 False
    """
    return storage.remove_subscription(topic_id, _serialize_target(target))


async def list_subscribers(topic_id: str) -> list[PlatformTarget]:
    """列出某主题的全部订阅目标（反序列化后的 PlatformTarget）。

    Args:
        topic_id: 主题 ID

    Returns:
        订阅目标列表
    """
    return [
        _deserialize_target(sub.target) for sub in storage.list_subscriptions(topic_id)
    ]


async def list_subscription_records(topic_id: str) -> list[Subscription]:
    """列出某主题的订阅记录（含目标可读标识与订阅时间）。

    用于管理命令「推送订阅者」展示订阅者列表。

    Args:
        topic_id: 主题 ID

    Returns:
        订阅记录列表
    """
    return storage.list_subscriptions(topic_id)


async def list_subscriptions_by_target(target: PlatformTarget) -> list[Subscription]:
    """按目标查询其订阅的全部主题记录（用于「我的订阅」）。

    Args:
        target: 查询目标（如 ``TargetQQGroup`` / ``TargetQQPrivate``）

    Returns:
        该目标订阅的主题记录列表
    """
    return storage.list_subscriptions_by_target(_serialize_target(target))


async def _do_send(target: PlatformTarget, msg: MessageFactory) -> bool:
    try:
        await msg.send_to(target)
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).error(f"推送消息到 {target_key(target)} 失败")
        return False
    return True


async def _dispatch(
    topic_id: str | None,
    targets: Sequence[PlatformTarget],
    msg: MessageFactory,
    dedup_key: str | None,
) -> SendReport:
    report = SendReport()
    for target in targets:
        ok = await _do_send(target, msg)
        storage.add_history(
            PushRecord(
                topic_id=topic_id,
                target=_serialize_target(target),
                dedup_key=dedup_key,
                content_preview=_content_preview(msg),
                ok=ok,
                error=None if ok else "发送失败",
                created_at=time.time(),
            ),
            max_count=plugin_config.push_max_history,
        )
        if ok:
            report.ok_count += 1
        else:
            report.fail_count += 1
            report.failed_targets.append(target)
    return report


async def send_to_topic(
    topic_id: str,
    content: Content,
    *,
    targets: Sequence[PlatformTarget] | None = None,
    dedup_key: str | None = None,
) -> SendReport:
    """向某主题的订阅目标推送消息。

    Args:
        topic_id: 主题 ID
        content: 推送内容（str 或 SAA ``MessageFactory``）
        targets: 指定推送目标；为 None 时推送给该主题全部订阅者
        dedup_key: 去重 key；窗口内已有同 key 的成功记录时跳过推送

    Returns:
        发送结果汇总（成功/失败数量、失败目标、是否去重跳过）
    """
    if dedup_key is not None and storage.has_recent_dedup(
        topic_id, dedup_key, plugin_config.push_dedup_window_seconds
    ):
        return SendReport(skipped=True)

    if targets is None:
        targets = await list_subscribers(topic_id)

    return await _dispatch(topic_id, targets, _normalize_content(content), dedup_key)


async def send_to_targets(
    targets: Sequence[PlatformTarget],
    content: Content,
    *,
    dedup_key: str | None = None,
) -> SendReport:
    """直接向指定目标列表推送消息（不查询订阅关系）。

    Args:
        targets: 目标列表
        content: 推送内容（str 或 SAA ``MessageFactory``）
        dedup_key: 去重 key；窗口内已有同 key 的成功记录时跳过推送

    Returns:
        发送结果汇总（成功/失败数量、失败目标、是否去重跳过）
    """
    return await _dispatch(None, targets, _normalize_content(content), dedup_key)
