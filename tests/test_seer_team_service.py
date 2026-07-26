from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.config.models.seer import TeamQueryConfig
from ironsbot.services.seer.team import (
    SeerTeamQueryService,
    TeamQueryActor,
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
    total_boss_dmg: int = 9999
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

    async def get_team_info(self, _team_id: int) -> TeamInfo:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeHeadless:
    def __init__(self, result: TeamInfo | Exception) -> None:
        self.game = FakeGame(result)
        self.available = False

    def get_game(self) -> FakeGame:
        return self.game

    async def mark_available(self, **_kwargs: object) -> None:
        self.available = True

    async def mark_unavailable(self, *_args: object, **_kwargs: object) -> None:
        return None


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
        TeamQueryConfig(sections=["basic", "resource"]),
        cast("HeadlessService", headless),
        lambda _code: None,
        cast("TeamResourceService", team_resource),
    )
    return service, headless, team_resource


def test_team_service_parses_unique_ids_before_validation() -> None:
    service, _headless, _resource = _service()

    assert service.parse_team_ids(
        "战队123456 99 123456 2000000001 654321"
    ) == (123456, 99, 2000000001, 654321)


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
    assert "【设施等级】" not in message
    assert headless.available
    assert not resource.offered


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

    assert await service.query(
        (TEAM_ID,),
        TeamQueryActor(user_id=1, group_id=None, can_manage=False),
    ) == "❌ 战队 123456 查询超时，请稍后再试。"


@pytest.mark.asyncio
async def test_team_service_rejects_invalid_id_before_io() -> None:
    service, headless, _resource = _service()

    message = await service.query(
        (1,),
        TeamQueryActor(user_id=1, group_id=456, can_manage=True),
    )

    assert "100000 ~ 2000000000" in message
    assert not headless.available
