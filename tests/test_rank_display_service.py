from pathlib import Path

from ironsbot.config.models.seer import RankQueryConfig
from ironsbot.core.onebot_references import OneBotReferenceResolver
from ironsbot.integrations.storage.rank_display import SqliteRankDisplayStore
from ironsbot.services.seer.rank_display import RankDisplayService

GROUP_ID = 987654321
USER_ID = 1234567890
STORED_LIMIT = 50
ALIAS_LIMIT = 30


def _rank_config() -> RankQueryConfig:
    return RankQueryConfig(
        display_limit=10,
        max_display_limit=100,
        display_limits={},
    )


def _service(
    config: RankQueryConfig,
    aliases: dict[str, int],
    state_path: Path,
) -> RankDisplayService:
    return RankDisplayService(
        config,
        OneBotReferenceResolver(aliases, {}),
        SqliteRankDisplayStore(state_path),
    )


def test_rank_display_limit_prefers_stored_group_limit(
    tmp_path: Path,
) -> None:
    service = _service(_rank_config(), {}, tmp_path / "qq_state.sqlite")

    service.set_group_limit(
        group_id=GROUP_ID,
        user_id=USER_ID,
        limit=STORED_LIMIT,
    )

    assert service.limit_for_group(GROUP_ID) == STORED_LIMIT


def test_rank_display_limit_uses_configured_alias(
    tmp_path: Path,
) -> None:
    rank_config = _rank_config().model_copy(
        update={"display_limits": {"example": ALIAS_LIMIT}}
    )
    service = _service(
        rank_config,
        {"example": GROUP_ID},
        tmp_path / "qq_state.sqlite",
    )

    assert service.limit_for_group(GROUP_ID) == ALIAS_LIMIT
