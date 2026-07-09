from ironsbot.integrations.headless_seer.command_id import COMMAND_ID
from ironsbot.integrations.headless_seer.core.register import packet_register
from ironsbot.integrations.headless_seer.packets import (
    AllSvrListInfo,
    DailyRankList,
    SimpleTeamInfo,
    UserInfo,
)


def test_integrations_headless_packets_register_protocol_types() -> None:
    assert packet_register[COMMAND_ID.COMMEND_ONLINE] is AllSvrListInfo
    assert packet_register[COMMAND_ID.TEAM_GET_INFO] is SimpleTeamInfo
    assert packet_register[COMMAND_ID.GET_DAILY_RANK_INFO] is DailyRankList
    assert packet_register[COMMAND_ID.GET_USER_INFO] is UserInfo
