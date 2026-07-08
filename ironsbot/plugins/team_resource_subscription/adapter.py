from typing import Any, NamedTuple

from ironsbot.services.seer.client import get_game_client
from ironsbot.services.seer.team import format_team_info


class TeamResourceResult(NamedTuple):
    team_id: int
    team_name: str
    message: str
    resource: int


def _format_team_info(info: Any) -> str:
    return format_team_info(info, {"basic", "resource"})


async def fetch_team_resource_result(team_id: int) -> TeamResourceResult:
    team_info = await get_game_client().get_team_info(team_id)
    return TeamResourceResult(
        team_id=team_info.team_id,
        team_name=team_info.name,
        message=_format_team_info(team_info),
        resource=team_info.score,
    )
