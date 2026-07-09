# SPDX-License-Identifier: MIT
from typing import Any

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
)

from ironsbot.config.loader import get_app_config
from ironsbot.services.bilibili.accounts import (
    account_display_label,
    account_nickname,
    account_uid,
    bili_accounts,
    resolve_account_reference,
)
from ironsbot.services.bilibili.preferences import (
    bili_push_subscription_key,
    normalize_push_mode_text,
    push_mode_label,
)
from ironsbot.services.bilibili.storage import push_preference_store
from ironsbot.services.bilibili.targets import (
    mode_for_target_account,
    target_rule,
)
from ironsbot.shared.messaging import finish_event_reply
from ironsbot.shared.messaging.push_subscription_models import (
    PushTargetType,
)
from ironsbot.shared.messaging.push_subscription_store import (
    PushUnsubscribeStore,
)
from ironsbot.shared.permissions import (
    can_manage_conversation_event,
)
from ironsbot.shared.plugin_system import PluginContext

BILI_PUSH_MODE_ACCOUNT_KEY = "_bili_push_mode_account"
BILI_PUSH_MODE_RAW_KEY = "_bili_push_mode_raw"


def _is_bili_push_mode_manager(event: MessageEvent) -> bool:
    return can_manage_conversation_event(event)


def _push_mode_target(event: MessageEvent) -> tuple[PushTargetType, int]:
    if isinstance(event, GroupMessageEvent):
        return "group", int(event.group_id)
    return "private", int(event.user_id)


def _bili_push_mode_usage() -> str:
    return (
        "用法：B站推送模式 <账号昵称> <内容|链接|默认>\n"
        "例：B站推送模式 赛尔号官方 链接\n"
        "例：B站推送模式 火火 内容\n"
        "例：B站推送模式 火火 默认"
    )


def _push_unsubscribe_store() -> PushUnsubscribeStore:
    return PushUnsubscribeStore(get_app_config().message.push_unsubscribe.data_path)


def _format_account_mode_line(
    *,
    target_type: PushTargetType,
    target_id: int,
    account: str,
    uid: int,
    unsubscribed_keys: set[str],
) -> str:
    mode = mode_for_target_account(target_type, target_id, account)
    mode_text = push_mode_label(mode)
    td_text = "，已 TD" if bili_push_subscription_key(uid) in unsubscribed_keys else ""
    return f"- {account_display_label(account, uid=uid)}：{mode_text}{td_text}"


async def handle_bili_accounts_action(
    event: MessageEvent,
    context: PluginContext,
    fallback_matcher: Any,
) -> None:
    matcher = context.matcher or fallback_matcher
    target_type, target_id = _push_mode_target(event)
    rule = target_rule(target_type, target_id)
    accounts = bili_accounts()

    lines = ["📺【B站账号】"]
    account_lines = "、".join(
        (
            f"{nickname}（{uid}）"
            if (nickname := account_nickname(name))
            else f"{name}={uid}"
        )
        for name, uid in accounts.items()
    )
    lines.append("账号库：" + account_lines)
    if rule is None:
        lines.append("当前会话未开启 B站推送。")
        await finish_event_reply(matcher, event, "\n".join(lines))
        return

    unsubscribed_keys = _push_unsubscribe_store().target_unsubscribed_keys(
        target_type,
        target_id,
    )
    lines.append("当前订阅：")
    for account in sorted(rule.accounts):
        uid = accounts[account]
        lines.append(
            _format_account_mode_line(
                target_type=target_type,
                target_id=target_id,
                account=account,
                uid=uid,
                unsubscribed_keys=unsubscribed_keys,
            )
        )
    lines.append("群主/管理员可发送：B站推送模式 <账号昵称> <内容|链接|默认>")
    await finish_event_reply(matcher, event, "\n".join(lines))


async def handle_bili_push_mode_action(
    event: MessageEvent,
    context: PluginContext,
    fallback_matcher: Any,
) -> None:
    matcher = context.matcher or fallback_matcher
    state = context.state if context.state is not None else {}

    if not _is_bili_push_mode_manager(event):
        await finish_event_reply(matcher, event, "❌ 仅群主、管理员或超级管理员可用。")
        return

    account_ref = str(state.get(BILI_PUSH_MODE_ACCOUNT_KEY, "") or "").strip()
    raw_mode = str(state.get(BILI_PUSH_MODE_RAW_KEY, "") or "")
    if not account_ref or not raw_mode.strip():
        await finish_event_reply(matcher, event, _bili_push_mode_usage())
        return

    account = resolve_account_reference(account_ref)
    uid = account_uid(account) if account is not None else None
    if account is None or uid is None:
        await finish_event_reply(
            matcher,
            event,
            f"❌ 未知 B站账号：{account_ref}\n可发送“B站账号”查看账号库。",
        )
        return

    target_type, target_id = _push_mode_target(event)
    rule = target_rule(target_type, target_id)
    current_mode = mode_for_target_account(target_type, target_id, account)
    if current_mode is None:
        await finish_event_reply(
            matcher,
            event,
            f"❌ 当前会话没有订阅 B站账号：{account_ref}。",
        )
        return
    if rule is None or account not in rule.accounts:
        await finish_event_reply(matcher, event, _bili_push_mode_usage())
        return

    try:
        mode = normalize_push_mode_text(raw_mode)
    except ValueError:
        await finish_event_reply(matcher, event, _bili_push_mode_usage())
        return

    store = push_preference_store()
    if mode is None:
        store.clear_mode(target_type, target_id, uid)
    else:
        store.set_mode(target_type, target_id, uid, mode)

    effective_mode = mode_for_target_account(target_type, target_id, account)
    scope = "当前群" if target_type == "group" else "当前私聊"
    account_text = account_display_label(account, uid=uid)
    await finish_event_reply(
        matcher,
        event,
        f"已设置{scope} B站账号 {account_text}推送模式："
        f"{push_mode_label(mode)}。\n"
        f"当前生效模式：{push_mode_label(effective_mode)}。",
    )
