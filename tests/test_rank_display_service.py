from pathlib import Path

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.integrations.storage.rank_display import SqliteRankDisplayStore
from ironsbot.services.seer.rank_display import RankDisplayService

GROUP_ID = 987654321
USER_ID = 1234567890
STORED_LIMIT = 50
ALIAS_LIMIT = 30
DEFAULT_LIMIT = 10


def _group(group_id: int = GROUP_ID) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _actor(user_id: int = USER_ID) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _rank_config() -> RankQueryConfig:
    return RankQueryConfig(
        display_limit=DEFAULT_LIMIT,
        max_display_limit=100,
        display_limits={},
    )


def _service(
    config: RankQueryConfig,
    configured_limits: dict[ConversationRef, int],
    state_path: Path,
) -> RankDisplayService:
    return RankDisplayService(
        config,
        configured_limits,
        SqliteRankDisplayStore(state_path),
    )


def test_rank_display_limit_prefers_stored_group_limit(
    tmp_path: Path,
) -> None:
    service = _service(_rank_config(), {}, tmp_path / "qq_state.sqlite")

    service.set_conversation_limit(
        _group(),
        _actor(),
        limit=STORED_LIMIT,
    )

    assert service.limit_for_conversation(_group()) == STORED_LIMIT


def test_rank_display_limit_uses_configured_alias(
    tmp_path: Path,
) -> None:
    service = _service(
        _rank_config(),
        {_group(): ALIAS_LIMIT},
        tmp_path / "qq_state.sqlite",
    )

    assert service.limit_for_conversation(_group()) == ALIAS_LIMIT


def test_rank_display_limits_are_isolated_by_platform(tmp_path: Path) -> None:
    service = _service(_rank_config(), {}, tmp_path / "qq_state.sqlite")
    onebot_group = _group()
    official_group = ConversationRef(Platform.QQ_OFFICIAL, "group", str(GROUP_ID))

    service.set_conversation_limit(onebot_group, _actor(), STORED_LIMIT)

    assert service.limit_for_conversation(onebot_group) == STORED_LIMIT
    assert service.limit_for_conversation(official_group) == DEFAULT_LIMIT
