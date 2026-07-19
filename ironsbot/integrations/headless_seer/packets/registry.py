# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from ..command_id import COMMAND_ID
from .login import AllSvrListInfo, RangeSvrInfo
from .peak import DailyRankList
from .team import SimpleTeamInfo
from .user import MoreInfo, OnLineInfos, UserForeverValue, UserInfo

PACKET_BODY_TYPES: Final[Mapping[int, type[Any]]] = MappingProxyType(
    {
        COMMAND_ID.COMMEND_ONLINE: AllSvrListInfo,
        COMMAND_ID.RANGE_ONLINE: RangeSvrInfo,
        COMMAND_ID.TEAM_GET_INFO: SimpleTeamInfo,
        COMMAND_ID.GET_DAILY_RANK_INFO: DailyRankList,
        COMMAND_ID.GET_USER_INFO: UserInfo,
        COMMAND_ID.GET_MORE_USER_INFO: MoreInfo,
        COMMAND_ID.USER_FOREVER_VALUE: UserForeverValue,
        COMMAND_ID.SEE_ONLINE: OnLineInfos,
    }
)
