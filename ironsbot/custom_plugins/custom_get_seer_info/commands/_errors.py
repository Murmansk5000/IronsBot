# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import logger

from ironsbot.plugins.db_sync.manager import db_manager
from ironsbot.plugins.headless_seer.exception import SocketRecvError
from ironsbot.plugins.seer_data.db import ErrorCodeGetter


def format_socket_recv_error(error: SocketRecvError) -> str:
    result_code = error.head.result
    try:
        sessions = next(db_manager.get_all_sessions())
        error_code = ErrorCodeGetter(sessions, str(result_code))
    except Exception:  # noqa: BLE001
        logger.opt(exception=True).warning("failed to resolve Seer error code")
        error_code = []

    if error_code:
        return f"请求失败：{error_code[0].message}"

    return f"请求失败，错误码：{result_code}"
