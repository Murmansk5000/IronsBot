from typing import Any, NamedTuple


class TeamShortcutResult(NamedTuple):
    message: str
    resource: int


def _format_team_info(info: Any) -> str:
    slogan = info.slogan or "（无）"
    notice = info.notice or "（无）"
    return (
        f"🏰【{info.name}】\n"
        f"战队ID：{info.team_id}\n"
        f"等级：{info.new_team_level}\n"
        f"队长：{info.leader}（米米号）\n"
        f"成员数：{info.member_count}\n"
        f"战队资源：{info.score}\n"
        f"标语：{slogan}\n"
        f"公告：{notice}"
    )


async def fetch_team_shortcut_result(team_id: int) -> TeamShortcutResult:
    from ironsbot.plugins.headless_seer.manager import client_manager

    team_info = await client_manager.get_client().get_team_info(team_id)
    return TeamShortcutResult(
        message=_format_team_info(team_info),
        resource=team_info.score,
    )
