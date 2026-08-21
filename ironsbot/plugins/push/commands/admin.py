# SPDX-License-Identifier: MIT
from datetime import datetime, timezone
from typing import Annotated, NoReturn

from nonebot import on_command
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent
from nonebot.matcher import Matcher
from nonebot.params import Depends
from nonebot.permission import SUPERUSER, Permission
from nonebot_plugin_saa import TargetQQGroup

from ironsbot.utils.parse_arg import parse_string_arg
from ironsbot.utils.rule import no_reply

from ..config import plugin_config
from ..models import target_key
from ..service import (
    create_topic,
    delete_topic,
    get_topic,
    is_registered_static_topic,
    list_subscription_records,
    send_to_targets,
    send_to_topic,
    update_topic,
)


async def _is_push_admin(bot: Bot, event: Event) -> bool:
    """检查事件是否来自有推送管理权限的超级用户。"""
    return await _push_admin_error(bot, event) is None


async def _push_admin_error(bot: Bot, event: Event) -> str | None:
    """返回权限失败提示；权限通过时返回 ``None``。"""
    if not await SUPERUSER(bot, event):
        return "❌您不是超级用户，无法管理推送"

    allowed_group_ids = plugin_config.push_admin_manage_group_ids
    if allowed_group_ids and not (
        isinstance(event, GroupMessageEvent)
        and event.group_id in allowed_group_ids
    ):
        return "❌当前会话未获推送管理权限"

    return None


async def _require_push_admin(matcher: Matcher, bot: Bot, event: Event) -> None:
    """在命令规则通过后检查管理权限，并向调用者返回失败原因。"""
    if await PUSH_ADMIN_PERMISSION(bot, event):
        return

    await matcher.finish(
        await _push_admin_error(bot, event) or "❌当前会话未获推送管理权限"
    )


AdminPermissionCheck = Annotated[None, Depends(_require_push_admin)]


# Permission 中多个 checker 是“任一通过”，不能直接组合 SUPERUSER 和群检查；
# 将两个必须同时满足的条件封装为单个 checker，保留原有权限语义。
# 不把它直接传给 matcher.permission：Permission 会先于命令 Rule 执行，
# 由依赖在 Rule 通过后调用，才能只对实际管理命令返回错误信息。
PUSH_ADMIN_PERMISSION = Permission(_is_push_admin)

#: 命令参数分段判断所需的最小段数
_MIN_PARTS = 2


def _format_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


create_matcher = on_command(
    "推送新建",
    rule=no_reply(),
    priority=1,
    block=True,
)


@create_matcher.handle()
async def handle_create(
    matcher: Matcher,
    arg: str = Depends(parse_string_arg),
    _: AdminPermissionCheck = None,
) -> NoReturn:
    parts = arg.split(maxsplit=2)
    if len(parts) < _MIN_PARTS:
        await matcher.finish("用法：推送新建 <主题ID> <名称> [描述...]")
    topic_id, name = parts[0], parts[1]
    description = parts[2] if len(parts) > _MIN_PARTS else ""
    if await get_topic(topic_id) is not None:
        await matcher.finish(f"❌主题【{topic_id}】已存在")
    if await create_topic(topic_id, name=name, description=description):
        await matcher.finish(f"✅已创建主题【{topic_id}】{name}")
    await matcher.finish(f"❌创建主题【{topic_id}】失败")


delete_matcher = on_command(
    "推送删除",
    rule=no_reply(),
    priority=1,
    block=True,
)


@delete_matcher.handle()
async def handle_delete(
    matcher: Matcher,
    arg: str = Depends(parse_string_arg),
    _: AdminPermissionCheck = None,
) -> NoReturn:
    topic_id = arg.strip()
    if not topic_id:
        await matcher.finish("用法：推送删除 <主题ID>")
    if is_registered_static_topic(topic_id):
        await matcher.finish(
            f"❌主题【{topic_id}】由代码注册，无法删除；可先使用“推送停用”"
        )
    if await delete_topic(topic_id):
        await matcher.finish(f"✅已删除主题【{topic_id}】及其全部订阅")
    await matcher.finish(f"❌主题【{topic_id}】不存在")


enable_matcher = on_command(
    "推送启用",
    rule=no_reply(),
    priority=1,
    block=True,
)


@enable_matcher.handle()
async def handle_enable(
    matcher: Matcher,
    arg: str = Depends(parse_string_arg),
    _: AdminPermissionCheck = None,
) -> NoReturn:
    topic_id = arg.strip()
    if not topic_id:
        await matcher.finish("用法：推送启用 <主题ID>")
    if await update_topic(topic_id, enabled=True):
        await matcher.finish(f"✅已启用主题【{topic_id}】")
    await matcher.finish(f"❌主题【{topic_id}】不存在")


disable_matcher = on_command(
    "推送停用",
    rule=no_reply(),
    priority=1,
    block=True,
)


@disable_matcher.handle()
async def handle_disable(
    matcher: Matcher,
    arg: str = Depends(parse_string_arg),
    _: AdminPermissionCheck = None,
) -> NoReturn:
    topic_id = arg.strip()
    if not topic_id:
        await matcher.finish("用法：推送停用 <主题ID>")
    if await update_topic(topic_id, enabled=False):
        await matcher.finish(f"✅已停用主题【{topic_id}】")
    await matcher.finish(f"❌主题【{topic_id}】不存在")


subscribers_matcher = on_command(
    "推送订阅者",
    rule=no_reply(),
    priority=1,
    block=True,
)


@subscribers_matcher.handle()
async def handle_subscribers(
    matcher: Matcher,
    arg: str = Depends(parse_string_arg),
    _: AdminPermissionCheck = None,
) -> NoReturn:
    topic_id = arg.strip()
    if not topic_id:
        await matcher.finish("用法：推送订阅者 <主题ID>")
    topic = await get_topic(topic_id)
    if topic is None:
        await matcher.finish(f"❌主题【{topic_id}】不存在")
    subs = await list_subscription_records(topic_id)
    if not subs:
        await matcher.finish(f"📭主题【{topic.name}】暂无订阅者")
    lines = [f"📋主题【{topic.name}】订阅者（{len(subs)}）："]
    lines.extend(
        f"  • {sub.target_key}（{_format_time(sub.subscribed_at)}）" for sub in subs
    )
    await matcher.finish("\n".join(lines))


push_matcher = on_command(
    "推送",
    rule=no_reply(),
    priority=1,
    block=True,
)


@push_matcher.handle()
async def handle_push(
    matcher: Matcher,
    arg: str = Depends(parse_string_arg),
    _: AdminPermissionCheck = None,
) -> NoReturn:
    parts = arg.split(maxsplit=1)
    if len(parts) < _MIN_PARTS:
        await matcher.finish("用法：推送 <主题ID> <内容>")
    topic_id, content = parts
    topic = await get_topic(topic_id)
    if topic is None:
        await matcher.finish(f"❌主题【{topic_id}】不存在")
    report = await send_to_topic(topic_id, content)
    if report.skipped:
        await matcher.finish("⏭️已跳过：去重窗口内已有相同推送")
    result = (
        f"📤已向【{topic.name}】推送：成功 {report.ok_count}，失败 {report.fail_count}"
    )
    if report.failed_targets:
        result += "\n失败目标：" + "、".join(
            target_key(t) for t in report.failed_targets
        )
    await matcher.finish(result)


direct_matcher = on_command(
    "推送直发",
    rule=no_reply(),
    priority=1,
    block=True,
)


@direct_matcher.handle()
async def handle_direct(
    matcher: Matcher,
    arg: str = Depends(parse_string_arg),
    _: AdminPermissionCheck = None,
) -> NoReturn:
    parts = arg.split(maxsplit=1)
    if len(parts) < _MIN_PARTS or not parts[0].isdigit():
        await matcher.finish("用法：推送直发 <群号> <内容>")
    group_id = int(parts[0])
    report = await send_to_targets([TargetQQGroup(group_id=group_id)], parts[1])
    if report.ok_count:
        await matcher.finish(f"✅已发到群 {group_id}")
    await matcher.finish(f"❌直发到群 {group_id} 失败")
