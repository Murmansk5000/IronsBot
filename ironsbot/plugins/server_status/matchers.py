# SPDX-License-Identifier: MIT
from __future__ import annotations

from nonebot.permission import SUPERUSER
from nonebot.plugin import on_fullmatch

from ironsbot.shared.matcher_priority import get_matcher_priority
from ironsbot.utils.rule import no_reply

from .metadata import (
    ADMIN_SERVER_STATUS_COMMAND,
    BOT_RESTART_COMMANDS,
    DISABLED_BARE_ADMIN_COMMAND,
    DOCKER_UPDATE_COMMANDS,
    NORMAL_SERVER_STATUS_COMMAND,
)

normal_server_status_matcher = on_fullmatch(
    NORMAL_SERVER_STATUS_COMMAND,
    rule=no_reply(),
    priority=get_matcher_priority("server_status", 0),
    block=True,
)
disabled_bare_admin_status_matcher = on_fullmatch(
    DISABLED_BARE_ADMIN_COMMAND,
    rule=no_reply(),
    priority=get_matcher_priority("server_status", 0),
    block=True,
)
admin_server_status_matcher = on_fullmatch(
    ADMIN_SERVER_STATUS_COMMAND,
    rule=no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("server_status_admin", 1),
    block=True,
)
bot_restart_matcher = on_fullmatch(
    BOT_RESTART_COMMANDS,
    rule=no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("server_status_admin", 1),
    block=True,
)
docker_update_matcher = on_fullmatch(
    DOCKER_UPDATE_COMMANDS,
    rule=no_reply(),
    permission=SUPERUSER,
    priority=get_matcher_priority("server_status_admin", 1),
    block=True,
)

__all__ = [
    "admin_server_status_matcher",
    "bot_restart_matcher",
    "disabled_bare_admin_status_matcher",
    "docker_update_matcher",
    "normal_server_status_matcher",
]
