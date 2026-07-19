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


def _service(
    *,
    config: HelpConfig | None = None,
    group_aliases: dict[str, int] | None = None,
    user_aliases: dict[str, int] | None = None,
) -> HelpHintService:
    return HelpHintService(
        config or HelpConfig(),
        group_aliases or {},
        user_aliases or {},
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
