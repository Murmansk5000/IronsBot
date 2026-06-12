import sqlite3
from pathlib import Path

from nonebot import on_message
from nonebot.adapters import Bot, Event
from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    Message,
    MessageEvent,
    MessageSegment,
)
from nonebot.rule import Rule
from nonebot.typing import T_State

from ironsbot.shared.messaging.reply_limits import (
    TEXT_SEND_APIS,
    build_reply_line_limit_decision,
    can_manage_reply_line_limit,
    group_id_for_send_api,
    limit_onebot_message,
    parse_reply_line_limit_arg,
)
from ironsbot.shared.messaging.reply_limits import (
    limit_text_lines as service_limit_text_lines,
)
from ironsbot.shared.plugin_system import (
    PluginContext,
    dispatch_plugin,
    register_plugin,
)
from ironsbot.utils.rule import no_reply

from .config import get_reply_config
from ironsbot.shared.messaging.text import (
    build_message,
    strip_command_prefix,
)

REPLY_LINE_LIMIT_ARG_KEY = "_message_reply_line_limit_arg"
REPLY_LINE_LIMIT_PLUGIN_NAME = "message_reply_line_limit"


def _cache_path() -> Path:
    path = get_reply_config().limit_path
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect_cache() -> sqlite3.Connection:
    conn = sqlite3.connect(_cache_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS group_reply_line_limits (
            group_id INTEGER PRIMARY KEY,
            max_lines INTEGER NOT NULL,
            updated_by INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def _default_reply_line_limit() -> int | None:
    config = get_reply_config()
    value = config.default_lines
    if value < 0:
        return None
    return max(
        config.min_lines,
        min(value, config.max_lines),
    )


def get_group_reply_line_limit(group_id: int) -> int | None:
    with _connect_cache() as conn:
        row = conn.execute(
            """
            SELECT max_lines FROM group_reply_line_limits
            WHERE group_id = ?
            """,
            (group_id,),
        ).fetchone()

    if row is None:
        return _default_reply_line_limit()
    return int(row[0])


def set_group_reply_line_limit(
    group_id: int,
    max_lines: int,
    updated_by: int,
) -> None:
    with _connect_cache() as conn:
        conn.execute(
            """
            INSERT INTO group_reply_line_limits
            (group_id, max_lines, updated_by)
            VALUES (?, ?, ?)
            ON CONFLICT(group_id) DO UPDATE SET
                max_lines = excluded.max_lines,
                updated_by = excluded.updated_by,
                updated_at = CURRENT_TIMESTAMP
            """,
            (group_id, max_lines, updated_by),
        )
        conn.commit()


def clear_group_reply_line_limit(group_id: int) -> None:
    with _connect_cache() as conn:
        conn.execute(
            """
            DELETE FROM group_reply_line_limits
            WHERE group_id = ?
            """,
            (group_id,),
        )
        conn.commit()


async def _is_reply_line_limit_command(event: Event, state: T_State) -> bool:
    command = strip_command_prefix(event.get_plaintext())
    if command is None:
        return False

    arg = parse_reply_line_limit_arg(command)
    if arg is None:
        return False

    state[REPLY_LINE_LIMIT_ARG_KEY] = arg
    return True


def _reply_line_limit_for_event(event: MessageEvent | None) -> int | None:
    if isinstance(event, GroupMessageEvent):
        return get_group_reply_line_limit(event.group_id)
    return _default_reply_line_limit()


def reply_line_limit_for_target(
    *,
    group_id: int | None = None,
) -> int | None:
    if group_id is not None:
        return get_group_reply_line_limit(group_id)
    return _default_reply_line_limit()


def limit_text_lines(text: str, max_lines: int | None) -> str:
    return service_limit_text_lines(text, max_lines)


def limit_message_by_reply_lines(
    message: str | Message | MessageSegment,
    *,
    event: MessageEvent | None = None,
    group_id: int | None = None,
) -> str | Message | MessageSegment:
    if isinstance(message, (Message, MessageSegment)):
        return message

    max_lines = (
        reply_line_limit_for_target(group_id=group_id)
        if group_id is not None
        else _reply_line_limit_for_event(event)
    )
    return limit_text_lines(message, max_lines)


_reply_line_limit_api_hook_state = {"registered": False}


def _limit_onebot_message(
    message: object,
    *,
    group_id: int | None,
) -> object:
    max_lines = reply_line_limit_for_target(group_id=group_id)
    return limit_onebot_message(message, max_lines=max_lines)


async def _limit_reply_lines_before_send(
    bot: Bot,  # noqa: ARG001
    api: str,
    data: dict[str, object],
) -> None:
    if api not in TEXT_SEND_APIS:
        return

    message = data.get("message")
    if message is None:
        return

    data["message"] = _limit_onebot_message(
        message,
        group_id=group_id_for_send_api(api, data),
    )


def setup_reply_line_limit_api_hook() -> None:
    if _reply_line_limit_api_hook_state["registered"]:
        return

    Bot.on_calling_api(_limit_reply_lines_before_send)
    _reply_line_limit_api_hook_state["registered"] = True


reply_line_limit_matcher = on_message(
    rule=Rule(_is_reply_line_limit_command) & no_reply(),
    priority=5,
    block=True,
)


async def _finish_reply_line_limit(
    matcher: object,
    event: MessageEvent,
    message: str | Message,
) -> None:
    at_user_ids = (event.user_id,) if isinstance(event, GroupMessageEvent) else ()
    await matcher.finish(build_message(message, at_user_ids=at_user_ids))


class MessageReplyLineLimitPlugin:
    name = REPLY_LINE_LIMIT_PLUGIN_NAME
    feature = "text"
    enabled = True

    async def handle(self, event: MessageEvent, context: PluginContext) -> None:
        matcher = context.matcher or reply_line_limit_matcher
        if not isinstance(event, GroupMessageEvent):
            await _finish_reply_line_limit(
                matcher,
                event,
                "请在群聊中设置本群回复行数。",
            )

        state = context.state if context.state is not None else {}
        raw_arg = str(state.get(REPLY_LINE_LIMIT_ARG_KEY) or "").strip()
        current_limit = get_group_reply_line_limit(event.group_id)
        config = get_reply_config()
        decision = build_reply_line_limit_decision(
            raw_arg=raw_arg,
            current_limit=current_limit,
            can_manage=can_manage_reply_line_limit(event),
            min_lines=config.min_lines,
            max_allowed_lines=config.max_lines,
        )

        if decision.should_clear:
            clear_group_reply_line_limit(event.group_id)

        if decision.should_set and decision.max_lines is not None:
            set_group_reply_line_limit(
                event.group_id,
                decision.max_lines,
                event.user_id,
            )

        await _finish_reply_line_limit(matcher, event, decision.message)


register_plugin(MessageReplyLineLimitPlugin())


@reply_line_limit_matcher.handle()
async def handle_reply_line_limit_command(
    event: MessageEvent,
    state: T_State,
) -> None:
    await dispatch_plugin(
        plugin_name=REPLY_LINE_LIMIT_PLUGIN_NAME,
        event=event,
        matcher=reply_line_limit_matcher,
        state=state,
    )
