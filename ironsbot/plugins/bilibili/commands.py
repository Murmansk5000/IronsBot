from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    PrivateMessageEvent,
)
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.config import get_app_config
from ironsbot.services.bilibili.auth import is_bili_auth_invalid
from ironsbot.services.bilibili.cache import (
    get_saved_cookie,
    list_dynamic_history,
    save_target_dynamic_history,
)
from ironsbot.services.bilibili.client import fetch_dynamic_feed
from ironsbot.services.bilibili.menu import (
    DYNAMIC_IDS_STATE_KEY,
    build_dynamic_detail_for_selection,
    build_dynamic_menu_text,
    dynamic_record_ids,
)
from ironsbot.services.bilibili.parser import (
    target_dynamics_from_response,
)
from ironsbot.services.bilibili.permissions import (
    is_bili_superuser,
    is_dynamic_query_allowed,
    is_dynamic_update_allowed,
)
from ironsbot.services.bilibili.preferences import (
    bili_push_subscription_key,
    normalize_push_mode_text,
    push_mode_label,
)
from ironsbot.services.bilibili.state import (
    account_display_label,
    account_nickname,
    account_uid,
    bili_accounts,
    mode_for_target_account,
    push_preference_store,
    query_uids_for_event,
    resolve_account_reference,
    target_rule,
)
from ironsbot.shared.features import is_event_feature_allowed
from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.shared.messaging import (
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
)
from ironsbot.shared.messaging.push_subscriptions import (
    PushTargetType,
    PushUnsubscribeStore,
)
from ironsbot.shared.messaging.text import command_text_matches, strip_command_prefix
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .auth import send_bili_login_qrcode_to_superusers
from .config import get_bili_config
from .service import run_check_logic

DYNAMIC_CONVERSATION_NAMESPACE = "bilibili_dynamic_menu"
DYNAMIC_MENU_COMMANDS = ("动态",)
DYNAMIC_UPDATE_COMMANDS = ("动态刷新", "动态更新", "刷新动态", "更新动态")
DYNAMIC_SELECT_COMMANDS = tuple(str(number) for number in range(1, 11))
BILI_ACCOUNT_COMMANDS = ("B站账号", "B站账户", "b站账号", "b站账户")
BILI_PUSH_MODE_COMMANDS = ("B站推送模式", "B站动态模式", "b站推送模式", "b站动态模式")
BILI_PLUGIN_NAME = "bili"
BILI_PUSH_MODE_ACCOUNT_KEY = "_bili_push_mode_account"
BILI_PUSH_MODE_RAW_KEY = "_bili_push_mode_raw"


async def _is_dynamic_menu_command(event: MessageEvent) -> bool:
    if not is_dynamic_query_allowed(event):
        return False

    return command_text_matches(
        event.get_plaintext(),
        DYNAMIC_MENU_COMMANDS,
    )


async def _is_update_dynamic_command(event: MessageEvent) -> bool:
    command = strip_command_prefix(event.get_plaintext())
    if command is None:
        return False

    if not command_text_matches(
        command,
        DYNAMIC_UPDATE_COMMANDS,
    ):
        return False

    return is_dynamic_update_allowed(event)


async def _is_bili_account_command(event: MessageEvent) -> bool:
    if not (
        is_dynamic_query_allowed(event)
        or is_event_feature_allowed(event, "bili_push")
    ):
        return False

    return command_text_matches(event.get_plaintext(), BILI_ACCOUNT_COMMANDS)


def _parse_bili_push_mode_command(text: str) -> tuple[str, str] | None:
    command = strip_command_prefix(text)
    if command is None:
        command = text.strip()

    lowered = command.lower()
    for prefix in BILI_PUSH_MODE_COMMANDS:
        if not lowered.startswith(prefix.lower()):
            continue
        rest = command[len(prefix) :].strip()
        if not rest:
            return ("", "")

        parts = rest.split(maxsplit=1)
        account = parts[0].strip()
        mode_text = parts[1].strip() if len(parts) > 1 else ""
        return (account, mode_text)

    return None


async def _is_bili_push_mode_command(
    event: MessageEvent,
    state: T_State,
) -> bool:
    parsed = _parse_bili_push_mode_command(event.get_plaintext())
    if parsed is None:
        return False

    account, raw_mode = parsed
    state[BILI_PUSH_MODE_ACCOUNT_KEY] = account
    state[BILI_PUSH_MODE_RAW_KEY] = raw_mode
    return True


def _is_dynamic_select_reply(event: MessageEvent) -> bool:
    return command_text_matches(event.get_plaintext(), DYNAMIC_SELECT_COMMANDS)


dynamic_menu_matcher = on_message(
    rule=Rule(_is_dynamic_menu_command) & no_reply(),
    priority=get_matcher_priority("bilibili", 1),
    block=True,
)

update_dynamic_matcher = on_message(
    rule=Rule(_is_update_dynamic_command) & no_reply(),
    priority=get_matcher_priority("bilibili", 1),
    block=True,
)

bili_account_matcher = on_message(
    rule=Rule(_is_bili_account_command) & no_reply(),
    priority=get_matcher_priority("bilibili", 1),
    block=True,
)

bili_push_mode_matcher = on_message(
    rule=Rule(_is_bili_push_mode_command) & no_reply(),
    priority=get_matcher_priority("bilibili", 1),
    block=True,
)


class BiliMonitorPlugin:
    name = BILI_PLUGIN_NAME
    feature = "bili_query"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        if context.action == "menu":
            await _handle_dynamic_menu(event, context)
            return
        if context.action == "update":
            await _handle_update_dynamic(event)
            return
        if context.action == "select":
            await _handle_dynamic_select(event, context)
            return
        if context.action == "accounts":
            await _handle_bili_accounts(event, context)
            return
        if context.action == "push_mode":
            await _handle_bili_push_mode(event, context)
            return


register_plugin(BiliMonitorPlugin())


async def _wait_dynamic_select(
    matcher: Any,
    event: MessageEvent,
) -> None:
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=DYNAMIC_CONVERSATION_NAMESPACE,
        handlers=[handle_dynamic_select],
        reply_check=_is_dynamic_select_reply,
    )


async def _handle_dynamic_menu(
    event: MessageEvent,
    context: PluginContext,
) -> None:
    matcher = context.matcher or dynamic_menu_matcher
    state = context.state if context.state is not None else {}
    try:
        query_uids = query_uids_for_event(event)
        logger.info(
            f"Bilibili dynamic menu query: user={event.user_id} uids={query_uids}"
        )
        if not query_uids:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📭 当前会话没有配置可查询的 B 站账号。",
            )

        response, res_json = await fetch_dynamic_feed(get_saved_cookie())
        if is_bili_auth_invalid(response.status_code, res_json):
            await send_bili_login_qrcode_to_superusers(
                "用户查询动态时发现 B 站登录失效"
            )
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "⚠️ B 站 Cookie 已失效，请超级管理员重新登录。",
            )

        target_dynamics = target_dynamics_from_response(
            res_json,
            query_uids,
            newest_first=True,
        )
        if target_dynamics:
            save_target_dynamic_history(
                target_dynamics,
                suppress_patterns=get_bili_config().filters.suppress_push_patterns,
            )

        records = list_dynamic_history(limit=10, uids=query_uids)
        if not records:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📭 没有可展示的历史动态。",
            )

        state[DYNAMIC_IDS_STATE_KEY] = dynamic_record_ids(records)

        logger.info(
            f"user {event.user_id} fetched Bilibili dynamic menu for {query_uids}"
        )
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=DYNAMIC_CONVERSATION_NAMESPACE,
            handlers=[handle_dynamic_select],
            reply_check=_is_dynamic_select_reply,
            prompt=Message(build_dynamic_menu_text(records)),
        )

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Bilibili dynamic menu failed: {e}")
        await finish_event_reply(
            dynamic_menu_matcher,
            event,
            "❌ 获取动态列表失败。",
        )


async def _handle_update_dynamic(event: MessageEvent) -> None:
    if not is_bili_superuser(event.user_id):
        await finish_event_reply(
            update_dynamic_matcher,
            event,
            "❌ 仅超级管理员可用。",
        )

    try:
        logger.info(f"superuser {event.user_id} manually refreshed Bilibili")
        await send_event_reply(
            update_dynamic_matcher,
            event,
            "⚡ 正在刷新动态...",
        )

        did_run = await run_check_logic(is_startup_check=True, force=True)
        if not did_run:
            await finish_event_reply(
                update_dynamic_matcher,
                event,
                "⏳ 动态刷新正在进行中，请稍后再试。",
            )

        await finish_event_reply(
            update_dynamic_matcher,
            event,
            "✅ 动态刷新完成。",
        )

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"manual Bilibili dynamic refresh failed: {e}")
        await finish_event_reply(
            update_dynamic_matcher,
            event,
            "❌ 动态刷新失败。",
        )


def _is_bili_push_mode_manager(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        role = getattr(event.sender, "role", None)
        return role in {"owner", "admin"} or is_bili_superuser(event.user_id)

    if isinstance(event, PrivateMessageEvent):
        return is_bili_superuser(event.user_id)

    return False


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


async def _handle_bili_accounts(
    event: MessageEvent,
    context: PluginContext,
) -> None:
    matcher = context.matcher or bili_account_matcher
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


async def _handle_bili_push_mode(
    event: MessageEvent,
    context: PluginContext,
) -> None:
    matcher = context.matcher or bili_push_mode_matcher
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


@dynamic_menu_matcher.handle()
async def handle_dynamic_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="menu",
    )


@update_dynamic_matcher.handle()
async def handle_update_dynamic(event: MessageEvent) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=update_dynamic_matcher,
        action="update",
    )


@bili_account_matcher.handle()
async def handle_bili_account(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="accounts",
    )


@bili_push_mode_matcher.handle()
async def handle_bili_push_mode(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="push_mode",
    )


async def _handle_dynamic_select(
    event: MessageEvent,
    context: PluginContext,
) -> None:
    matcher = context.matcher or dynamic_menu_matcher
    state = context.state if context.state is not None else {}
    try:
        cached_ids = state.get(DYNAMIC_IDS_STATE_KEY, [])
        selection = build_dynamic_detail_for_selection(
            cached_ids,
            event.get_plaintext(),
        )
        if selection.status == "expired":
            await finish_event_reply(
                matcher,
                event,
                "⏳ 会话已超时，请重新发送“动态”。",
            )

        if selection.status == "invalid":
            await send_event_reply(
                matcher,
                event,
                "请输入数字。",
            )
            await _wait_dynamic_select(matcher, event)
            return

        if selection.status == "out_of_range":
            await send_event_reply(
                matcher,
                event,
                f"请输入 1~{selection.available_count} 之间的数字。",
            )
            await _wait_dynamic_select(matcher, event)
            return

        if selection.status == "missing":
            await finish_event_reply(
                matcher,
                event,
                "❌ 没找到这条历史动态，请重新发送“动态”。",
            )

        if selection.status == "parse_failed":
            await finish_event_reply(
                matcher,
                event,
                "❌ 动态详情解析失败。",
            )

        if selection.message:
            await send_event_reply(
                matcher,
                event,
                selection.message,
            )

        await _wait_dynamic_select(matcher, event)

    except FinishedException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.error(f"Bilibili dynamic number select failed: {e}")
        await finish_event_reply(
            matcher,
            event,
            "❌ 动态详情解析失败。",
        )


async def handle_dynamic_select(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=BILI_PLUGIN_NAME,
        event=event,
        matcher=matcher,
        state=state,
        action="select",
    )
