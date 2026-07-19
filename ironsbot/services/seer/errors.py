# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from collections.abc import Callable

from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)

ErrorMessageLookup = Callable[[int], str | None]
PLAYER_NOT_FOUND_RESULT_CODES = {101105}
DATABASE_UNAVAILABLE_MESSAGE = (
    "❌数据尚未载入，暂时无法使用这个命令。\n"
    "请将命令和这条消息反馈给机器人维护者。"
)
SERVER_UNAVAILABLE_PLAYER_QUERY_MESSAGE = (
    "查询需要连接赛尔号游戏服务器；当前服务器维护或未开放，请稍后再试。"
)


def format_socket_recv_error(
    error: SocketRecvError,
    error_message: ErrorMessageLookup | None = None,
) -> str:
    result_code = error.head.result
    message = error_message(result_code) if error_message is not None else None
    if message:
        return f"请求失败：{message}"
    return f"请求失败，错误码：{result_code}"


def format_player_query_error(
    player_id: int,
    error: SocketRecvError | NotLoggedInError | DisconnectedError,
    error_message: ErrorMessageLookup | None = None,
) -> str:
    if isinstance(error, SocketRecvError):
        result_code = error.head.result
        if result_code in PLAYER_NOT_FOUND_RESULT_CODES:
            return f"❌ 米米号 {player_id} 不存在或用户信息不可查询。"
        return (
            f"❌ 米米号 {player_id} "
            f"{format_socket_recv_error(error, error_message)}"
        )

    return (
        f"❌ 米米号 {player_id} 暂时查不了："
        f"{SERVER_UNAVAILABLE_PLAYER_QUERY_MESSAGE}"
    )
