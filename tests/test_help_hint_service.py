from dataclasses import dataclass

from ironsbot.core.features import HelpConfig
from ironsbot.core.help import DIRECT_COMMAND_HELP_HINT_TEXT
from ironsbot.services.messaging.help_hint import (
    HelpHintService,
    is_poke_at_bot,
)


@dataclass(slots=True)
class FakePokeEvent:
    self_id: int
    target_id: int


@dataclass(slots=True)
class FakeFeatures:
    group_features: dict[int, set[str]]
    private_features: dict[int, set[str]]
    group_allowed_features: dict[tuple[int, int], set[str]] | None = None

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


def _service(
    *,
    config: HelpConfig | None = None,
    group_aliases: dict[str, int] | None = None,
    user_aliases: dict[str, int] | None = None,
    features: FakeFeatures | None = None,
) -> HelpHintService:
    return HelpHintService(
        config or HelpConfig(),
        group_aliases or {},
        user_aliases or {},
        features,
        chooser=lambda hints: hints[0],
    )


def test_help_hint_text_mentions_help_command() -> None:
    assert (
        DIRECT_COMMAND_HELP_HINT_TEXT
        == "直接发送指令即可使用机器人功能；使用“帮助”指令获取帮助。"
    )


def test_is_poke_at_bot_checks_poke_target() -> None:
    assert is_poke_at_bot(FakePokeEvent(self_id=100, target_id=100))
    assert not is_poke_at_bot(FakePokeEvent(self_id=100, target_id=200))


def test_group_poke_reply_prefers_configured_group_alias(
) -> None:
    service = _service(
        group_aliases={"example": 987654321},
        config=HelpConfig(poke_replies={"example": "自定义戳一戳回复"}),
    )

    assert service.get_poke_reply(group_id=987654321, user_id=1) == (
        "自定义戳一戳回复"
    )
    assert service.get_poke_reply(group_id=876543210, user_id=1) is None


def test_group_poke_reply_accepts_numeric_group_id(
) -> None:
    service = _service(
        config=HelpConfig(poke_replies={"987654321": "数字群号回复"}),
    )

    assert service.get_poke_reply(group_id=987654321, user_id=1) == "数字群号回复"


def test_user_poke_reply_accepts_chinese_user_alias(
) -> None:
    service = _service(
        user_aliases={"示例昵称": 1234567890},
        config=HelpConfig(
            poke_user_replies={"示例昵称": "用户专属回复"},
        ),
    )

    assert service.get_poke_reply(group_id=None, user_id=1234567890) == (
        "用户专属回复"
    )
    assert service.get_poke_reply(group_id=None, user_id=9876543210) is None


def test_user_poke_reply_takes_priority_over_group_reply(
) -> None:
    service = _service(
        group_aliases={"example": 987654321},
        user_aliases={"example_user": 1234567890},
        config=HelpConfig(
            poke_replies={"example": "群专属回复"},
            poke_user_replies={"example_user": "用户专属回复"},
        ),
    )

    assert (
        service.get_poke_reply(group_id=987654321, user_id=1234567890)
        == "用户专属回复"
    )
    assert service.get_poke_reply(
        group_id=987654321,
        user_id=2345678901,
    ) == "群专属回复"


def test_help_hint_limiter_allows_three_group_hints_per_minute(
) -> None:
    service = _service()
    now = 100.0

    assert service.can_send(987654321, now=now)
    assert service.can_send(987654321, now=now)
    assert service.can_send(987654321, now=now)
    assert not service.can_send(987654321, now=now)

    now = 160.0
    assert service.can_send(987654321, now=now)


def test_help_hint_limiter_counts_groups_independently(
) -> None:
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

    assert service.get_default_poke_hint(
        group_id=987654321,
        user_id=1,
    ) == "发送“精灵名配置”获取配置图。\n发送“帮助”可查看全部指令。"


def test_default_poke_hint_uses_private_feature_policy() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={},
            private_features={1234567890: {"server_status_query"}},
        )
    )

    assert service.get_default_poke_hint(
        group_id=None,
        user_id=1234567890,
    ) == "发送“开服了吗”查询维护状态。\n发送“帮助”可查看全部指令。"
    assert service.get_default_poke_hint(group_id=None, user_id=1) is None


def test_team_resource_poke_hint_is_group_only() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"team_resource_subscription"}},
            private_features={1234567890: {"team_resource_subscription"}},
        )
    )

    assert service.get_default_poke_hint(
        group_id=987654321,
        user_id=1,
    ) == "发送“战队”查看本群战队订阅。\n发送“帮助”可查看全部指令。"
    assert service.get_default_poke_hint(group_id=None, user_id=1234567890) is None


def test_group_poke_hint_uses_the_poking_users_permission() -> None:
    service = _service(
        features=FakeFeatures(
            group_features={987654321: {"bili_query"}},
            private_features={},
            group_allowed_features={(100, 987654321): {"bili_query"}},
        )
    )

    assert service.get_default_poke_hint(
        group_id=987654321,
        user_id=100,
    ) == "发送“动态”查看订阅动态。\n发送“帮助”可查看全部指令。"
    assert service.get_default_poke_hint(group_id=987654321, user_id=200) is None


def test_default_poke_hint_excludes_ignored_help_plugins() -> None:
    service = _service(
        config=HelpConfig(ignored_plugins=["seer_query"]),
        features=FakeFeatures(
            group_features={987654321: {"seer_player", "pet_config"}},
            private_features={},
        ),
    )

    assert service.get_default_poke_hint(
        group_id=987654321,
        user_id=1,
    ) == "发送“精灵名配置”获取配置图。\n发送“帮助”可查看全部指令。"
