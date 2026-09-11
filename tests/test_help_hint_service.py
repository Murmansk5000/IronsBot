from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ironsbot.config.models.messaging import PokeConfig
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.core.onebot_references import OneBotReferenceResolver
from ironsbot.runtime.commands import (
    CommandAccess,
    CommandCatalog,
    CommandContext,
    CommandDescriptor,
)
from ironsbot.runtime.plugins import PluginDefinition
from ironsbot.services.messaging.help_hint import (
    CommandHintCandidate,
    CommandHintChooser,
    HelpHintService,
    is_poke_at_bot,
)
from ironsbot.services.messaging.poke_promotions import PokePromotionService

_INITIAL_PROMOTION_WEIGHT = 5.0
_FIVE_DAY_PROMOTION_WEIGHT = 3.0
_TEN_DAY_PROMOTION_WEIGHT = 2.0


@dataclass(slots=True)
class FakePokeEvent:
    self_id: int
    target_id: int


@dataclass(slots=True)
class FakeFeatures:
    group_features: dict[int, set[str]]
    private_features: dict[int, set[str]]
    group_allowed_features: dict[tuple[int, int], set[str]] | None = None
    superusers: set[int] | None = None

    def group_has_feature(self, group_id: int, feature: str) -> bool:
        return feature in self.group_features.get(group_id, set())

    def is_group_feature_allowed(
        self,
        user_id: int,
        group_id: int,
        feature: str,
    ) -> bool:
        if self.group_allowed_features is None:
            return self.group_has_feature(group_id, feature)
        return feature in self.group_allowed_features.get((user_id, group_id), set())

    def is_private_feature_allowed(self, user_id: int, feature: str) -> bool:
        return feature in self.private_features.get(user_id, set())

    def is_superuser(self, user_id: int) -> bool:
        return user_id in (self.superusers or set())


def _catalog() -> CommandCatalog:
    catalog = CommandCatalog()
    definitions = (
        PluginDefinition(
            id="pet_config",
            commands=(
                CommandDescriptor(
                    id="pet_config.query",
                    plugin_id="pet_config",
                    section="查询",
                    examples=("雷伊配置",),
                    description="查询已收录的精灵配置图",
                    features_any=("pet_config",),
                    show_in_poke=True,
                ),
            ),
        ),
        PluginDefinition(
            id="server_status",
            commands=(
                CommandDescriptor(
                    id="server_status.query",
                    plugin_id="server_status",
                    section="查询",
                    examples=("开服了吗",),
                    description="查询维护状态",
                    features_any=("server_status_query",),
                    show_in_poke=True,
                ),
            ),
        ),
        PluginDefinition(
            id="activity",
            commands=(
                CommandDescriptor(
                    id="activity.ending",
                    plugin_id="activity",
                    section="查询",
                    examples=("快结束活动",),
                    description="查询即将结束的活动",
                    features_any=("seer_activity_query",),
                    show_in_poke=True,
                ),
                CommandDescriptor(
                    id="activity.current",
                    plugin_id="activity",
                    section="超级管理员",
                    examples=("/当前活动",),
                    description="查询完整活动列表",
                    features_any=("seer_activity_query",),
                    access=(CommandAccess(audience="superuser"),),
                    show_in_poke=True,
                ),
            ),
        ),
        PluginDefinition(
            id="team_resource",
            commands=(
                CommandDescriptor(
                    id="team_resource.query",
                    plugin_id="team_resource",
                    section="查询",
                    examples=("战队",),
                    description="查看战队订阅",
                    features_any=("team_resource_subscription",),
                    access=(CommandAccess(scope="group"),),
                    show_in_poke=True,
                ),
            ),
        ),
        PluginDefinition(
            id="bilibili",
            commands=(
                CommandDescriptor(
                    id="bilibili.dynamic",
                    plugin_id="bilibili",
                    section="查询",
                    examples=("动态",),
                    description="查看订阅动态",
                    features_any=("bili_query",),
                    show_in_poke=True,
                ),
            ),
        ),
        PluginDefinition(
            id="rank_help",
            commands=(
                CommandDescriptor(
                    id="rank.display_limit",
                    plugin_id="rank_help",
                    section="群管理",
                    examples=("/榜单显示 20",),
                    description="设置榜单默认显示名次",
                    features_any=("seer_rank",),
                    access=(CommandAccess("group", "group_manager"),),
                    show_in_poke=True,
                ),
            ),
        ),
    )
    catalog.load(
        definitions,
        known_features={
            "bili_query",
            "pet_config",
            "seer_activity_query",
            "seer_rank",
            "server_status_query",
            "team_resource_subscription",
        },
    )
    return catalog


def _service(  # noqa: PLR0913 - concise test fixture options
    *,
    config: PokeConfig | None = None,
    ignored_plugins: tuple[str, ...] = (),
    group_aliases: dict[str, int] | None = None,
    user_aliases: dict[str, int] | None = None,
    features: FakeFeatures | None = None,
    promotions: PokePromotionService | None = None,
    chooser: CommandHintChooser | None = None,
) -> HelpHintService:
    catalog = _catalog()

    def candidates(
        group_id: int | None,
        user_id: int,
        group_role: str | None,
        ignored_plugins: tuple[str, ...],
    ):
        if features is None:
            return ()
        return catalog.poke_candidates_for_context(
            CommandContext(
                user_id=user_id,
                group_id=group_id,
                group_role=group_role,
            ),
            features,
            ignored_plugins=ignored_plugins,
        )

    return HelpHintService(
        config=config or PokeConfig(),
        ignored_plugins=ignored_plugins,
        references=OneBotReferenceResolver(
            group_aliases=group_aliases or {},
            user_aliases=user_aliases or {},
        ),
        poke_hint_candidates=candidates,
        promotions=promotions,
        chooser=(
            chooser
            if chooser is not None
            else lambda candidates, _weights: candidates[0]
        ),
    )


def test_help_hint_text_mentions_help_command() -> None:
    assert (
        DIRECT_COMMAND_HELP_HINT_TEXT
        == "别 @ 我，@ 我不会执行任何指令。"
        "删除 @ 后直接发送需要使用的指令；不会用就发送‘帮助’。"
    )


def test_is_poke_at_bot_checks_poke_target() -> None:
    assert is_poke_at_bot(FakePokeEvent(self_id=100, target_id=100))
    assert not is_poke_at_bot(FakePokeEvent(self_id=100, target_id=200))


def test_group_poke_reply_prefers_configured_group_alias() -> None:
    service = _service(
        group_aliases={"example": 987654321},
        config=PokeConfig(group_replies={"example": "自定义戳一戳回复"}),
    )

    assert service.get_poke_reply(group_id=987654321, user_id=1) == (
        "自定义戳一戳回复"
    )
    assert service.get_poke_reply(group_id=876543210, user_id=1) is None


def test_group_poke_reply_accepts_numeric_group_id() -> None:
    service = _service(
        config=PokeConfig(group_replies={"987654321": "数字群号回复"}),
    )

    assert service.get_poke_reply(group_id=987654321, user_id=1) == "数字群号回复"


def test_user_poke_reply_accepts_chinese_user_alias() -> None:
    service = _service(
        user_aliases={"示例昵称": 1234567890},
        config=PokeConfig(user_replies={"示例昵称": "用户专属回复"}),
    )

    assert service.get_poke_reply(group_id=None, user_id=1234567890) == (
        "用户专属回复"
    )
    assert service.get_poke_reply(group_id=None, user_id=9876543210) is None


def test_user_poke_reply_takes_priority_over_group_reply() -> None:
    service = _service(
        group_aliases={"example": 987654321},
        user_aliases={"example_user": 1234567890},
        config=PokeConfig(
            group_replies={"example": "群专属回复"},
            user_replies={"example_user": "用户专属回复"},
        ),
    )

    assert (
        service.get_poke_reply(group_id=987654321, user_id=1234567890)
        == "用户专属回复"
    )
    assert (
        service.get_poke_reply(group_id=987654321, user_id=2345678901)
        == "群专属回复"
    )


@pytest.mark.parametrize("field", ["group_replies", "user_replies"])
@pytest.mark.parametrize("replies", [{" ": "reply"}, {"123": " "}])
def test_poke_config_rejects_empty_targets_or_replies(
    field: str, replies: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match="non-empty group/user refs and messages"):
        PokeConfig.model_validate({field: replies})


def test_poke_config_trims_reply_targets_and_text() -> None:
    config = PokeConfig(
        group_replies={" example ": " group reply "},
        user_replies={" 123 ": " user reply "},
    )
    assert config.group_replies == {"example": "group reply"}
    assert config.user_replies == {"123": "user reply"}


@pytest.mark.parametrize("field", ["window_seconds", "max_per_window"])
def test_poke_config_rejects_invalid_rate_limits(field: str) -> None:
    with pytest.raises(ValueError):
        PokeConfig.model_validate({field: 0})


def test_poke_limiter_uses_custom_window_and_count() -> None:
    service = _service(config=PokeConfig(window_seconds=10.0, max_per_window=1))
    assert service.can_send(987654321, now=100.0)
    assert not service.can_send(987654321, now=109.0)
    assert service.can_send(987654321, now=111.0)


def test_help_hint_limiter_allows_three_group_hints_per_minute() -> None:
    service = _service()
    now = 100.0

    assert service.can_send(987654321, now=now)
    assert service.can_send(987654321, now=now)
    assert service.can_send(987654321, now=now)
    assert not service.can_send(987654321, now=now)

    assert service.can_send(987654321, now=160.0)


def test_help_hint_limiter_counts_groups_independently() -> None:
    service = _service()

    assert service.can_send(1, now=100.0)
    assert service.can_send(1, now=100.0)
    assert service.can_send(1, now=100.0)
    assert not service.can_send(1, now=100.0)
    assert service.can_send(2, now=100.0)


def test_default_poke_hint_only_uses_features_enabled_in_group() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"pet_config"}},
            private_features={},
        )
    )

    assert service.get_default_poke_hint(group_id=987654321, user_id=1) == (
        "发送“雷伊配置”查询已收录的精灵配置图。\n发送“帮助”可查看全部指令。"
    )


def test_default_poke_hint_uses_private_feature_policy() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={},
            private_features={1234567890: {"server_status_query"}},
        )
    )

    assert service.get_default_poke_hint(group_id=None, user_id=1234567890) == (
        "发送“开服了吗”查询维护状态。\n发送“帮助”可查看全部指令。"
    )
    assert service.get_default_poke_hint(group_id=None, user_id=1) is None


def test_activity_poke_hint_excludes_superuser_only_command_for_regular_user() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"seer_activity_query"}},
            private_features={},
        )
    )

    assert service.get_default_poke_hint(group_id=987654321, user_id=1) == (
        "发送“快结束活动”查询即将结束的活动。\n发送“帮助”可查看全部指令。"
    )


def test_team_resource_poke_hint_is_group_only() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"team_resource_subscription"}},
            private_features={1234567890: {"team_resource_subscription"}},
        )
    )

    assert service.get_default_poke_hint(group_id=987654321, user_id=1) == (
        "发送“战队”查看战队订阅。\n发送“帮助”可查看全部指令。"
    )
    assert service.get_default_poke_hint(group_id=None, user_id=1234567890) is None


def test_group_poke_hint_uses_the_poking_users_permission() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"bili_query"}},
            private_features={},
            group_allowed_features={(100, 987654321): {"bili_query"}},
        )
    )

    assert service.get_default_poke_hint(group_id=987654321, user_id=100) == (
        "发送“动态”查看订阅动态。\n发送“帮助”可查看全部指令。"
    )
    assert service.get_default_poke_hint(group_id=987654321, user_id=200) is None


def test_default_poke_hint_excludes_ignored_plugins() -> None:
    service = _service(
        ignored_plugins=("seer_query",),
        features=FakeFeatures(
            group_features={987654321: {"pet_config"}},
            private_features={},
        ),
    )

    assert service.get_default_poke_hint(group_id=987654321, user_id=1) == (
        "发送“雷伊配置”查询已收录的精灵配置图。\n发送“帮助”可查看全部指令。"
    )


def test_group_manager_poke_hint_can_include_group_management_command() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"seer_rank"}},
            private_features={},
        )
    )

    assert service.get_default_poke_hint(group_id=987654321, user_id=1) is None
    assert service.get_default_poke_hint(
        group_id=987654321,
        user_id=1,
        group_role="owner",
    ) == (
        "发送“/榜单显示 20”设置榜单默认显示名次。\n"
        "发送“帮助”可查看全部指令。"
    )


def test_superuser_poke_hint_can_include_group_management_command() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"seer_rank"}},
            private_features={},
            superusers={1},
        )
    )

    assert service.get_default_poke_hint(group_id=987654321, user_id=1) == (
        "发送“/榜单显示 20”设置榜单默认显示名次。\n"
        "发送“帮助”可查看全部指令。"
    )


def test_new_poke_command_weight_decays_from_five_to_three() -> None:
    introduced_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    service = PokePromotionService(
        introduced_at={"server_status.query": introduced_at},
        initial_weight=_INITIAL_PROMOTION_WEIGHT,
        half_life_days=5.0,
    )

    assert service.weight_for("pet_config.query", now=introduced_at) == 1.0
    assert (
        service.weight_for("server_status.query", now=introduced_at)
        == _INITIAL_PROMOTION_WEIGHT
    )
    assert service.weight_for(
        "server_status.query",
        now=introduced_at + timedelta(days=5),
    ) == _FIVE_DAY_PROMOTION_WEIGHT
    assert service.weight_for(
        "server_status.query",
        now=introduced_at + timedelta(days=10),
    ) == _TEN_DAY_PROMOTION_WEIGHT


def test_poke_config_rejects_invalid_new_command_promotion_weights() -> None:
    with pytest.raises(ValueError):
        PokeConfig(new_command_initial_weight=0.5)
    with pytest.raises(ValueError):
        PokeConfig(new_command_half_life_days=0.0)


def test_missing_poke_promotion_manifest_uses_uniform_weights(
    tmp_path: Path,
) -> None:
    service = PokePromotionService.from_path(PokeConfig(), tmp_path / "missing.json")

    assert service.weight_for("seer.autocard.sanctuary") == 1.0


def test_default_poke_hint_passes_recency_weights_to_chooser() -> None:
    now = datetime(2026, 8, 1, tzinfo=timezone.utc)
    seen_weights: list[tuple[float, ...]] = []

    def choose_highest(
        candidates: Sequence[CommandHintCandidate],
        weights: Sequence[float],
    ) -> CommandHintCandidate:
        candidate_list = tuple(candidates)
        weight_list = tuple(weights)
        seen_weights.append(weight_list)
        return candidate_list[weight_list.index(max(weight_list))]

    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"pet_config", "server_status_query"}},
            private_features={},
        ),
        promotions=PokePromotionService(
            introduced_at={"server_status.query": now},
            initial_weight=_INITIAL_PROMOTION_WEIGHT,
            half_life_days=5.0,
        ),
        chooser=choose_highest,
    )

    assert service.get_default_poke_hint(group_id=987654321, user_id=1) == (
        "发送“开服了吗”查询维护状态。\n发送“帮助”可查看全部指令。"
    )
    assert seen_weights[0][0] == 1.0
    assert seen_weights[0][1] > 1.0
