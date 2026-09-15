from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.config.models.seer import TeamQueryConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.team import (
    SeerTeamQueryService,
    TeamBossActivityStatus,
    TeamQueryActor,
    format_team_info,
)
from ironsbot.services.seer.team_commands import build_team_query_operation

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ironsbot.services.operations.headless import HeadlessService
    from ironsbot.services.team.resource import TeamResourceService

TEAM_ID = 123456


def _actor(user_id: int = 1) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _group(group_id: int = 456) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _context(
    text: str,
    *,
    mentions: tuple[ActorRef, ...] = (),
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            Platform.ONEBOT,
            _actor(),
            _group(),
            "message-id",
            text,
            direct_mentions=mentions,
        ),
        mentions_bot=False,
    )


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

    async def get_team_info(self, _team_id: int) -> TeamInfo:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def get_user_info(self, _player_id: int) -> object:
        if isinstance(self._result, Exception):
            raise self._result
        return type("PlayerInfo", (), {"team_id": TEAM_ID})()


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
async def test_team_service_queries_and_formats_enabled_sections() -> None:
    service, headless, resource = _service()

    message = await service.query(
        (TEAM_ID,),
        TeamQueryActor(actor=_actor(), conversation=None, can_manage=False),
    )

    assert "【战队信息：测试战队】" in message
    assert "战队ID：123456" in message
    assert "战队等级：9" in message
    assert "战队资源：777" in message
    assert "战队 Boss：剩余能量 4/200｜活动状态：暂无法确认" in message
    assert "标语：一起冲" in message
    assert "公告：今晚集合" in message
    assert "【文本】" not in message
    assert "【设施等级】" not in message
    assert headless.available
    assert not resource.offered


@pytest.mark.asyncio
async def test_player_team_query_reuses_team_detail_service() -> None:
    service, headless, _resource = _service()

    message = await service.query_player_team(
        148758762,
        TeamQueryActor(actor=_actor(), conversation=None, can_manage=False),
    )

    assert "【战队信息：测试战队】" in message
    assert "战队ID：123456" in message
    assert headless.available


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "mentions"),
    [
        ("战队玩家一", ()),
        ("战队米米号148758762", ()),
        ("战队", (_actor(2),)),
    ],
)
async def test_team_command_resolves_player_references_and_structured_mentions(
    text: str,
    mentions: tuple[ActorRef, ...],
) -> None:
    service, _headless, _resource = _service()
    resolver = PlayerIdResolver(
        lambda reference, _conversation: (
            148758762 if reference in {"玩家一", "148758762"} else None
        ),
        lambda actor: 148758762 if actor == _actor(2) else None,
    )

    operation = build_team_query_operation(
        service, resolver, FeatureService({}, {}, frozenset()), PortableQuerySessions(),
    )
    reply = await operation(text, _context(text, mentions=mentions))
    assert isinstance(reply, OutboundMessage)
    message = cast("TextPart", reply.parts[0]).text

    assert "【战队信息：测试战队】" in message
    assert "战队ID：123456" in message


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
        TeamQueryActor(actor=_actor(), conversation=None, can_manage=False),
    )

    assert "一次最多查询 3 个战队" in message
    assert not headless.available


@pytest.mark.asyncio
async def test_team_service_adds_subscription_prompt_for_group_manager() -> None:
    service, _headless, resource = _service()

    message = await service.query(
        (TEAM_ID,),
        TeamQueryActor(actor=_actor(), conversation=_group(), can_manage=True),
    )

    assert message.endswith("订阅提示")
    assert resource.offered


@pytest.mark.asyncio
async def test_team_service_formats_timeout() -> None:
    service, _headless, _resource = _service(TimeoutError())

    assert (
        await service.query(
            (TEAM_ID,),
            TeamQueryActor(actor=_actor(), conversation=None, can_manage=False),
        )
        == "❌ 战队 123456 查询超时，请稍后再试。"
    )


@pytest.mark.asyncio
async def test_player_team_service_formats_timeout_as_player_query() -> None:
    service, _headless, _resource = _service(TimeoutError())

    assert await service.query_player_team(
        148758762,
        TeamQueryActor(actor=_actor(), conversation=None, can_manage=False),
    ) == "米米号 148758762 的所属战队查询超时，请稍后再试。"


@pytest.mark.asyncio
async def test_team_service_rejects_invalid_id_before_io() -> None:
    service, headless, _resource = _service()

    message = await service.query(
        (1,),
        TeamQueryActor(actor=_actor(), conversation=_group(), can_manage=True),
    )

    assert "100000 ~ 2000000000" in message
    assert not headless.available
