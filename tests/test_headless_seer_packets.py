from ironsbot.integrations.headless_seer.command_id import COMMAND_ID
from ironsbot.integrations.headless_seer.packets.login import AllSvrListInfo
from ironsbot.integrations.headless_seer.packets.peak import DailyRankList
from ironsbot.integrations.headless_seer.packets.registry import (
    PACKET_BODY_TYPES,
)
from ironsbot.integrations.headless_seer.packets.team import SimpleTeamInfo
from ironsbot.integrations.headless_seer.packets.user import UserInfo


def test_integrations_headless_packets_register_protocol_types() -> None:
    assert PACKET_BODY_TYPES[COMMAND_ID.COMMEND_ONLINE] is AllSvrListInfo
    assert PACKET_BODY_TYPES[COMMAND_ID.TEAM_GET_INFO] is SimpleTeamInfo
    assert PACKET_BODY_TYPES[COMMAND_ID.GET_DAILY_RANK_INFO] is DailyRankList
    assert PACKET_BODY_TYPES[COMMAND_ID.GET_USER_INFO] is UserInfo
