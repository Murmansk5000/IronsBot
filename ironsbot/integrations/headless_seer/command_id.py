# SPDX-License-Identifier: GPL-3.0-or-later
from typing import TYPE_CHECKING, Any, Final, NamedTuple

from .type_hint import CommandID

if TYPE_CHECKING:
    from .packets.login import AllSvrListInfo, RangeSvrInfo
    from .packets.peak import DailyRankList
    from .packets.team import SimpleTeamInfo
    from .packets.user import MoreInfo, OnLineInfos, UserForeverValue, UserInfo


class CommandIDNamedTuple(NamedTuple):
    GET_VERIFCODE: CommandID[Any] = CommandID(101)
    MAIN_LOGIN_IN: CommandID[Any] = CommandID(103)
    COMMEND_ONLINE: CommandID["AllSvrListInfo"] = CommandID(105)
    RANGE_ONLINE: CommandID["RangeSvrInfo"] = CommandID(106)
    CREATE_ROLE: CommandID[Any] = CommandID(108)
    SYS_ROLE: CommandID[Any] = CommandID(109)
    FENGHAO_TIME: CommandID[Any] = CommandID(111)

    LOGIN_IN: CommandID[Any] = CommandID(1001)
    GET_SESSION: CommandID[Any] = CommandID(1016)
    SEE_ONLINE: CommandID["OnLineInfos"] = CommandID(2157)

    TEAM_GET_INFO: CommandID["SimpleTeamInfo"] = CommandID(2917)
    GET_USER_INFO: CommandID["UserInfo"] = CommandID(2051)
    GET_MORE_USER_INFO: CommandID["MoreInfo"] = CommandID(2052)
    GET_DAILY_RANK_INFO: CommandID["DailyRankList"] = CommandID(4481)
    USER_FOREVER_VALUE: CommandID["UserForeverValue"] = CommandID(40002)
    SOCKET_RECONNECT: CommandID[Any] = CommandID(41463)


COMMAND_ID: Final[CommandIDNamedTuple] = CommandIDNamedTuple()
