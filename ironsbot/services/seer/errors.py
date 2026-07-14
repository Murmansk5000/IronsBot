# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import logger

from ironsbot.integrations.headless_seer.exception import (
    DisconnectedError,
    NotLoggedInError,
    SocketRecvError,
)

PLAYER_NOT_FOUND_RESULT_CODES = {101105}
SERVER_UNAVAILABLE_PLAYER_QUERY_MESSAGE = (
    "查询需要连接赛尔号游戏服务器；当前服务器维护或未开放，请稍后再试。"
)


def format_socket_recv_error(error: SocketRecvError) -> str:
    result_code = error.head.result
    try:
        from ironsbot.integrations.db_registry import db_manager
        from ironsbot.integrations.seer_data.getters import ErrorCodeGetter

        sessions = next(db_manager.get_all_sessions())
        error_code = ErrorCodeGetter(sessions, str(result_code))
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("failed to resolve Seer error code")
        error_code = []

    if error_code:
        return f"请求失败：{error_code[0].message}"

    return f"请求失败，错误码：{result_code}"


def format_player_query_error(
    player_id: int,
    error: SocketRecvError | NotLoggedInError | DisconnectedError,
) -> str:
    if isinstance(error, SocketRecvError):
        result_code = error.head.result
        if result_code in PLAYER_NOT_FOUND_RESULT_CODES:
            return f"❌ 米米号 {player_id} 不存在或用户信息不可查询。"
        return f"❌ 米米号 {player_id} {format_socket_recv_error(error)}"

    return (
        f"❌ 米米号 {player_id} 暂时查不了："
        f"{SERVER_UNAVAILABLE_PLAYER_QUERY_MESSAGE}"
    )
