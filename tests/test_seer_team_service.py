from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.config.models.seer import TeamQueryConfig
from ironsbot.services.operations.headless_errors import (
    DisconnectedError,
    SocketRecvError,
)
from ironsbot.services.seer.team import (
    SeerTeamQueryService,
    TeamBossActivityStatus,
    TeamQueryActor,
    format_team_info,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.team.resource import TeamResourceService

TEAM_ID = 123456


@dataclass(frozen=True)
class TeamInfo:
    name: str = "测试战队"
    team_id: int = TEAM_ID
    leader: int = 654321
    member_count: int = 42
    new_team_level: int = 9
    score: int = 777
    tech_center_level: int = 3
    bonus_center_level: int = 4
    res_center_level: int = 5
    total_boss_dmg: int = 196
    interest: int = 1
    join_flag: int = 2
    visit_flag: int = 3
    team_func_disalbed: int = 0
    drawing_uint: int = 123
    logo_bg: int = 11
    logo_icon: int = 22
    logo_color: int = 33
    txt_color: int = 44
    logo_word: str = "T"
    slogan: str = "一起冲"
    notice: str = "今晚集合"


class FakeOperations:
    @contextmanager
    def track(self, *_args: object, **_kwargs: object) -> Iterator[None]:
        yield


class FakeGame:
    user_id = 10001
    operations = FakeOperations()

    def __init__(self, result: TeamInfo | Exception) -> None:
        self._result = result
        self.player_result: SimpleNamespace | Exception = SimpleNamespace(
            team_id=TEAM_ID,
        )
        self.queried_teams: list[int] = []

    async def get_user_info(self, _player_id: int) -> SimpleNamespace:
        if isinstance(self.player_result, Exception):
            raise self.player_result
        return self.player_result

    async def get_team_info(self, _team_id: int) -> TeamInfo:
        self.queried_teams.append(_team_id)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeHeadless:
    def __init__(self, result: TeamInfo | Exception) -> None:
        self.game = FakeGame(result)
        self.available = False
        self.unavailable = False

    def get_game(self) -> FakeGame:
        return self.game

    async def mark_available(self, **_kwargs: object) -> None:
        self.available = True

    async def mark_unavailable(self, *_args: object, **_kwargs: object) -> None:
        self.unavailable = True


class FakeTeamResource:
    def __init__(self) -> None:
        self.offered = False

    def offer_subscription(self, **_kwargs: object) -> str:
        self.offered = True
        return "订阅提示"


def _service(
    result: TeamInfo | Exception = TeamInfo(),
) -> tuple[SeerTeamQueryService, FakeHeadless, FakeTeamResource]:
    headless = FakeHeadless(result)
    team_resource = FakeTeamResource()
    service = SeerTeamQueryService(
        TeamQueryConfig(),
        cast("HeadlessService", headless),
        lambda _code: None,
        cast("TeamResourceService", team_resource),
    )
    return service, headless, team_resource


def test_team_service_parses_unique_ids_before_validation() -> None:
    service, _headless, _resource = _service()

    assert service.parse_team_ids("战队123456 99 123456 2000000001 654321") == (
        123456,
        99,
        2000000001,
        654321,
    )


@pytest.mark.asyncio
async def test_player_team_query_reuses_team_details() -> None:
    service, headless, _ = _service()
    actor = TeamQueryActor(1, None, can_manage=False)
    reply = await service.query_player_team(148758762, actor)
    assert headless.game.queried_teams == [TEAM_ID]
    assert "战队 Boss：剩余能量 4/200｜活动状态：暂无法确认" in reply
    headless.available = False
    headless.game.player_result = SimpleNamespace(team_id=0)
    reply = await service.query_player_team(148758762, actor)
    assert "当前未加入战队" in reply
    assert headless.game.queried_teams == [TEAM_ID]
    assert headless.available


@pytest.mark.asyncio
async def test_player_team_query_formats_profile_timeout() -> None:
    service, headless, _ = _service()
    headless.game.player_result = TimeoutError()

    reply = await service.query_player_team(
        148758762,
        TeamQueryActor(1, None, can_manage=False),
    )

    assert reply == "米米号 148758762 的所属战队查询超时，请稍后再试。"
    assert headless.game.queried_teams == []


@pytest.mark.asyncio
async def test_player_team_query_formats_profile_disconnect() -> None:
    service, headless, _ = _service()
    headless.game.player_result = DisconnectedError("连接已断开")

    reply = await service.query_player_team(
        148758762,
        TeamQueryActor(1, None, can_manage=False),
    )

    assert reply == (
        "❌ 米米号 148758762 暂时查不了："
        "查询需要连接赛尔号游戏服务器；当前服务器维护或未开放，请稍后再试。"
    )
    assert headless.unavailable
    assert headless.game.queried_teams == []


@pytest.mark.asyncio
async def test_player_team_query_formats_profile_socket_error() -> None:
    service, headless, _ = _service()
    headless.game.player_result = SocketRecvError(SimpleNamespace(result=101105))

    reply = await service.query_player_team(
        148758762,
        TeamQueryActor(1, None, can_manage=False),
    )

    assert reply == "❌ 米米号 148758762 不存在或用户信息不可查询。"
    assert headless.game.queried_teams == []


@pytest.mark.asyncio
async def test_team_service_queries_and_formats_enabled_sections() -> None:
    service, headless, resource = _service()

    message = await service.query(
        (TEAM_ID,),
        TeamQueryActor(user_id=1, group_id=None, can_manage=False),
    )

    assert "【战队信息：测试战队】" in message
    assert "战队ID：123456" in message
    assert "战队等级：9" in message
    assert "战队资源：777" in message
    assert "战队 Boss：剩余能量 4/200｜活动状态：暂无法确认" in message
    assert "【文本】" not in message
    assert "标语：一起冲" in message
    assert "公告：今晚集合" in message
    assert (
        "战队 Boss：剩余能量 4/200｜活动状态：暂无法确认\n标语：一起冲"
        in message
    )
    assert "【设施等级】" not in message
    assert headless.available
    assert not resource.offered


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        (0, "剩余能量 200/200"),
        (196, "剩余能量 4/200"),
        (200, "剩余能量 0/200"),
        (-1, "能量数据异常（已削减能量：-1）"),
        (201, "能量数据异常（已削减能量：201）"),
    ],
)
def test_team_boss_energy_display(damage: int, expected: str) -> None:
    info = TeamInfo(total_boss_dmg=damage)
    message = format_team_info(
        info,
        {"basic", "resource", "facilities"},
        include_boss=True,
    )
    assert f"战队 Boss：{expected}｜活动状态：暂无法确认" in message
    assert message.count("战队 Boss：") == 1
    assert "战队Boss总伤害" not in message
    assert "【文本】" not in message
    assert "标语：" not in message
    assert "公告：" not in message
    assert "战队 Boss：" not in format_team_info(info, {"basic"})


@pytest.mark.parametrize(
    ("status", "label"),
    [
        (TeamBossActivityStatus.OPEN, "开启"),
        (TeamBossActivityStatus.CLOSED, "关闭"),
        (TeamBossActivityStatus.UNKNOWN, "暂无法确认"),
    ],
)
def test_team_boss_activity_status_is_explicit(
    status: TeamBossActivityStatus,
    label: str,
) -> None:
    message = format_team_info(
        TeamInfo(),
        {"resource"},
        include_boss=True,
        boss_activity_status=status,
    )
    assert f"活动状态：{label}" in message


def test_team_resource_format_does_not_include_active_query_details() -> None:
    message = format_team_info(TeamInfo(), {"basic", "resource"})
    assert "战队 Boss：" not in message
    assert "标语：" not in message
    assert "公告：" not in message


@pytest.mark.asyncio
async def test_team_service_rejects_more_than_three_ids_without_querying() -> None:
    service, headless, _resource = _service()

    message = await service.query(
        (123456, 234567, 345678, 456789),
        TeamQueryActor(user_id=1, group_id=None, can_manage=False),
    )

    assert "一次最多查询 3 个战队" in message
    assert not headless.available


@pytest.mark.asyncio
async def test_team_service_adds_subscription_prompt_for_group_manager() -> None:
    service, _headless, resource = _service()

    message = await service.query(
        (TEAM_ID,),
        TeamQueryActor(user_id=1, group_id=456, can_manage=True),
    )

    assert message.endswith("订阅提示")
    assert resource.offered


@pytest.mark.asyncio
async def test_team_service_formats_timeout() -> None:
    service, _headless, _resource = _service(TimeoutError())

    assert (
        await service.query(
            (TEAM_ID,),
            TeamQueryActor(user_id=1, group_id=None, can_manage=False),
        )
        == "❌ 战队 123456 查询超时，请稍后再试。"
    )


@pytest.mark.asyncio
async def test_team_service_rejects_invalid_id_before_io() -> None:
    service, headless, _resource = _service()

    message = await service.query(
        (1,),
        TeamQueryActor(user_id=1, group_id=456, can_manage=True),
    )

    assert "100000 ~ 2000000000" in message
    assert not headless.available
