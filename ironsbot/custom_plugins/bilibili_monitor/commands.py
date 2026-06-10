from datetime import datetime, timezone
from typing import Any

from nonebot import on_message
from nonebot.adapters.onebot.v11 import Message, MessageEvent
from nonebot.exception import FinishedException
from nonebot.log import logger
from nonebot.matcher import Matcher
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.custom_plugins.message_actions import (
    command_text_matches,
    enter_event_reply_conversation,
    finish_event_reply,
    send_event_reply,
    strip_command_prefix,
)

from .auth import is_bili_auth_invalid, send_bili_login_qrcode_to_superusers
from .cache import (
    DynamicHistoryRecord,
    get_dynamic_history_item,
    get_saved_cookie,
    list_dynamic_history,
    save_dynamic_history_item,
)
from .client import fetch_dynamic_feed
from .parser import (
    dynamic_brief,
    dynamic_suppression_reason,
    find_target_dynamics,
    item_author_mid,
    item_author_name,
    parse_single_item,
)
from .permissions import (
    is_bili_superuser,
    is_dynamic_query_allowed,
    is_dynamic_update_allowed,
)
from .service import run_check_logic
from .state import BILI_CONFIG

DYNAMIC_IDS_KEY = "_bilibili_dynamic_ids"
DYNAMIC_CONVERSATION_NAMESPACE = "bilibili_dynamic_menu"
DYNAMIC_MENU_COMMANDS = ("动态",)
DYNAMIC_UPDATE_COMMANDS = ("动态刷新", "动态更新", "刷新动态", "更新动态")
DYNAMIC_SELECT_COMMANDS = tuple(str(number) for number in range(1, 11))
DYNAMIC_MENU_TIMEOUT_SECONDS = 120


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


def _is_dynamic_select_reply(event: MessageEvent) -> bool:
    return command_text_matches(event.get_plaintext(), DYNAMIC_SELECT_COMMANDS)


dynamic_menu_matcher = on_message(
    rule=Rule(_is_dynamic_menu_command),
    priority=1,
    block=True,
)

update_dynamic_matcher = on_message(
    rule=Rule(_is_update_dynamic_command),
    priority=1,
    block=True,
)


def _build_menu_text(records: list[DynamicHistoryRecord]) -> str:
    reply_text = (
        "📋 【最新动态列表】\n"
        "👉 发送数字查看详情\n"
        "-------------------------\n"
    )

    for index, record in enumerate(records, start=1):
        time_str = (
            datetime.fromtimestamp(record.pub_ts, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
        suppressed_tag = "（未推送）" if record.suppressed else ""
        reply_text += (
            f"【{index}】 ⏰ {time_str}{suppressed_tag}\n"
            f"👤 {record.author_name}（UID：{record.uid}）\n"
            f"📝 {record.brief}\n"
        )

    return (
        reply_text
        + "-------------------------\n"
        + "💡 两分钟内有效"
    )


async def _wait_dynamic_select(
    matcher: Matcher,
    event: MessageEvent,
) -> None:
    await enter_event_reply_conversation(
        matcher,
        event,
        namespace=DYNAMIC_CONVERSATION_NAMESPACE,
        handlers=[handle_dynamic_select],
        reply_check=_is_dynamic_select_reply,
    )


def _save_fetched_dynamics(target_dynamics: list[tuple[int, dict[str, Any]]]) -> None:
    for pub_ts, item in target_dynamics:
        author_mid = item_author_mid(item)
        if not author_mid:
            continue

        suppression_reason = dynamic_suppression_reason(
            item,
            BILI_CONFIG.filters.suppress_push_patterns,
        )
        save_dynamic_history_item(
            item,
            pub_ts=pub_ts,
            author_mid=author_mid,
            author_name=item_author_name(item),
            brief=dynamic_brief(item),
            suppressed=bool(suppression_reason),
            suppression_reason=suppression_reason,
        )


@dynamic_menu_matcher.handle()
async def handle_dynamic_menu(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    try:
        await send_event_reply(
            dynamic_menu_matcher,
            event,
            "🔄 正在拉取 B 站动态...",
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

        items = res_json.get("data", {}).get("items", [])
        if not items:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📭 没有动态数据。",
            )

        target_dynamics = find_target_dynamics(items)
        if not target_dynamics:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📭 近期没有公开动态。",
            )

        target_dynamics.sort(key=lambda value: value[0], reverse=True)
        _save_fetched_dynamics(target_dynamics)

        records = list_dynamic_history(limit=10)
        if not records:
            await finish_event_reply(
                dynamic_menu_matcher,
                event,
                "📭 没有可展示的历史动态。",
            )

        state[DYNAMIC_IDS_KEY] = [record.dynamic_id for record in records]

        logger.info(f"user {event.user_id} fetched Bilibili dynamic menu")
        await enter_event_reply_conversation(
            matcher,
            event,
            namespace=DYNAMIC_CONVERSATION_NAMESPACE,
            handlers=[handle_dynamic_select],
            reply_check=_is_dynamic_select_reply,
            prompt=Message(_build_menu_text(records)),
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


@update_dynamic_matcher.handle()
async def handle_update_dynamic(event: MessageEvent) -> None:
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


async def handle_dynamic_select(
    matcher: Matcher,
    event: MessageEvent,
    state: T_State,
) -> None:
    try:
        select_num = int(event.get_plaintext().strip())
        cached_ids = state.get(DYNAMIC_IDS_KEY, [])
        if not cached_ids:
            await finish_event_reply(
                matcher,
                event,
                "⏳ 会话已超时，请重新发送“动态”。",
            )

        if select_num < 1 or select_num > len(cached_ids):
            await send_event_reply(
                matcher,
                event,
                f"请输入 1~{len(cached_ids)} 之间的数字。",
            )
            await _wait_dynamic_select(matcher, event)

        dynamic_id = str(cached_ids[select_num - 1])
        record = get_dynamic_history_item(dynamic_id)
        if record is None:
            await finish_event_reply(
                matcher,
                event,
                "❌ 没找到这条历史动态，请重新发送“动态”。",
            )

        final_message = parse_single_item(
            record.item,
            record.pub_ts,
            menu_mode=True,
            mode="full",
        )

        if final_message:
            await send_event_reply(
                matcher,
                event,
                final_message,
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
