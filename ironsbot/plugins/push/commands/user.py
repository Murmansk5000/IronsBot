# SPDX-License-Identifier: MIT
from typing import NoReturn

from nonebot.adapters import Bot, Event
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot_plugin_saa import PlatformTarget, extract_target

from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply, startswith_or_endswith

from ..group import matcher_group
from ..models import target_key
from ..service import (
    get_topic,
    list_subscriptions_by_target,
    list_topics,
    subscribe,
    unsubscribe,
)

subscribe_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(prefixes=("订阅",)) & no_reply()
)
unsubscribe_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(prefixes=("退订",)) & no_reply()
)
my_subscriptions_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(prefixes=("我的订阅",)) & no_reply()
)
topic_list_matcher = matcher_group.on_message(
    rule=startswith_or_endswith(prefixes=("主题列表",)) & no_reply()
)


async def _current_target(matcher: Matcher, bot: Bot, event: Event) -> PlatformTarget:
    try:
        return extract_target(event, bot)
    except Exception:  # noqa: BLE001
        await matcher.finish("❌无法识别当前会话的推送目标")


@subscribe_matcher.handle()
async def handle_subscribe(
    matcher: Matcher,
    bot: Bot,
    event: Event,
    arg: str = Depends(parse_string_arg),
) -> NoReturn:
    topic_id = arg.strip()
    if not topic_id:
        await matcher.finish("用法：订阅 <主题ID>（如：订阅公告）")
    topic = await get_topic(topic_id)
    if topic is None:
        await matcher.finish(f"❌主题【{topic_id}】不存在，发送“主题列表”查看可用主题")
    if not topic.enabled:
        await matcher.finish(f"❌主题【{topic.name}】当前已停用")
    if not topic.allow_subscribe:
        await matcher.finish(f"❌主题【{topic.name}】不支持自助订阅")
    target = await _current_target(matcher, bot, event)
    if await subscribe(topic_id, target):
        await matcher.finish(f"✅已订阅【{topic.name}】（{target_key(target)}）")
    await matcher.finish(f"💡当前会话已订阅过【{topic.name}】")


@unsubscribe_matcher.handle()
async def handle_unsubscribe(
    matcher: Matcher,
    bot: Bot,
    event: Event,
    arg: str = Depends(parse_string_arg),
) -> NoReturn:
    topic_id = arg.strip()
    if not topic_id:
        await matcher.finish("用法：退订 <主题ID>（如：退订公告）")
    target = await _current_target(matcher, bot, event)
    if await unsubscribe(topic_id, target):
        await matcher.finish(f"✅已退订主题【{topic_id}】")
    await matcher.finish(f"💡当前会话未订阅主题【{topic_id}】")


@my_subscriptions_matcher.handle()
async def handle_my_subscriptions(
    matcher: Matcher,
    bot: Bot,
    event: Event,
) -> NoReturn:
    target = await _current_target(matcher, bot, event)
    subs = await list_subscriptions_by_target(target)
    if not subs:
        await matcher.finish(
            "📭当前会话还没有订阅任何主题，发送“主题列表”查看可订阅主题"
        )
    lines = [f"📋当前会话订阅的主题（{len(subs)}）："]
    for sub in subs:
        topic = await get_topic(sub.topic_id)
        name = topic.name if topic else sub.topic_id
        status = "（已停用）" if topic and not topic.enabled else ""
        lines.append(f"  • {name} [{sub.topic_id}]{status}")
    await matcher.finish("\n".join(lines))


@topic_list_matcher.handle()
async def handle_topic_list(matcher: Matcher) -> NoReturn:
    topics = await list_topics()
    if not topics:
        await matcher.finish("📭暂无可用主题")
    lines = ["📋全部推送主题："]
    for topic in topics:
        status = "✅" if topic.enabled else "⛔"
        sub_ok = "可订阅" if topic.allow_subscribe else "仅管理"
        lines.append(f"{status} {topic.name} [{topic.id}]（{sub_ok}）")
        if topic.description:
            lines.append(f"   {topic.description}")
    await matcher.finish("\n".join(lines))
