# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

from ironsbot.core.commands import NormalizedStringList, string_list
from ironsbot.core.onebot_references import (  # noqa: TC001 - Pydantic resolves aliases
    OneBotReferenceList,
)
from ironsbot.core.rank_exclusions import (
    DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK,
    DEFAULT_TAOMEE_INTERNAL_USER_IDS,
    RANK_EXCLUSION_SUPPORTED_KEYS,
)
from ironsbot.core.seer_ids import PLAYER_ID_MAX, PLAYER_ID_MIN
from ironsbot.core.time import normalize_daily_time, normalized_daily_times

from .seer_lucky import (  # noqa: F401 - compatibility re-export
    LuckySkinWindowAccountConfig,
    LuckySkinWindowConfig,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

PLAYER_SECTION_KEYS: tuple[str, ...] = (
    "basic",
    "appearance",
    "social",
    "collection",
    "rank",
    "autocard",
    "local_rank",
    "achievement",
    "peak",
    "titles",
    "pets",
    "stages",
    "battle",
    "raw",
)
TEAM_SECTION_KEYS: tuple[str, ...] = (
    "basic",
    "resource",
    "facilities",
    "status",
    "logo",
    "text",
)
RANK_PAGE_REFRESH_TIME_ERROR = (
    "seer.rank.page_refresh.times must contain daily HH:MM:SS times"
)
LOCAL_RANK_REFRESH_TIME_ERROR = "seer.local_rank.time must use HH:MM:SS"
RANK_PAGE_REFRESH_INTERVAL_OFFSET_ERROR = (
    "seer.rank.page_refresh.interval_offset_minutes must be smaller than "
    "interval_minutes"
)
RANK_PAGE_REFRESH_PAGES_PER_RUN_MIN_ERROR = (
    "seer.rank.page_refresh.pages_per_run_min must not be greater than pages_per_run"
)
RANK_PAGE_REFRESH_ACTIVE_TIME_ERROR = (
    "seer.rank.page_refresh active_start/active_end must be HH:MM:SS times"
)
RANK_PAGE_REFRESH_ACTIVE_PAIR_ERROR = (
    "seer.rank.page_refresh.active_start and active_end must be configured together"
)
PLAYER_RANK_LOOKUP_TIMEOUT_ERROR = "player lookup total timeout must cover one page"
TEAM_RESOURCE_TIME_ERROR = (
    "seer.team_resource.times must contain daily HH:MM:SS times"
)
PLAYER_ACCOUNT_NAME_ERROR = "seer.player_accounts name must not be empty"
PLAYER_ACCOUNT_ALIASES_ERROR = (
    "seer.player_accounts aliases must not contain empty values"
)
DEFAULT_RANK_PAGE_REFRESH_TIMES = (
    "01:15:00",
    "01:45:00",
    "02:15:00",
    "02:45:00",
    "03:15:00",
    "03:45:00",
    "04:15:00",
    "04:45:00",
)
DEFAULT_RANK_PAGE_REFRESH_KEYS = (
    "图鉴积分",
    "成就点数",
    "精灵图鉴",
    "皮肤图鉴",
    "套装图鉴",
    "部件图鉴",
    "座驾图鉴",
    "刻印图鉴",
    "群星牌",
    "竞技段位",
    "狂野段位",
    "专家段位",
)
MAX_RANK_DISPLAY_LIMIT = 100
RANK_EXCLUSION_USER_ID_ERROR = "seer.rank.exclusions user IDs must be positive"
RANK_EXCLUSION_RANK_KEY_ERROR = (
    "seer.rank.exclusions.user_ids_by_rank contains an unsupported rank key"
)
RANK_LOOKUP_LIMIT_RANK_KEY_ERROR = (
    "seer.rank.lookup_limits contains an unsupported global rank key"
)
NEW_CONTENT_CATEGORY_KEYS = (
    "achievement",
    "pet",
    "pet_skin",
    "skill",
    "mintmark",
    "suit",
    "equip",
    "mount",
    "autocard_card",
    "autocard_role",
    "autocard_sanctuary_effect",
)
NEW_CONTENT_CATEGORY_ERROR = (
    "seer.new_content.expanded_categories contains an unsupported category"
)
NewContentCategoryKey = Literal[
    "achievement",
    "pet",
    "pet_skin",
    "skill",
    "mintmark",
    "suit",
    "equip",
    "mount",
    "autocard_card",
    "autocard_role",
    "autocard_sanctuary_effect",
]


class RankExclusionRankKeyError(ValueError):
    def __init__(self, unknown: set[str]) -> None:
        super().__init__(
            f"{RANK_EXCLUSION_RANK_KEY_ERROR}: {', '.join(sorted(unknown))}"
        )


class RankLookupLimitRankKeyError(ValueError):
    def __init__(self, unknown: set[str]) -> None:
        super().__init__(
            f"{RANK_LOOKUP_LIMIT_RANK_KEY_ERROR}: {', '.join(sorted(unknown))}"
        )


class RankLookupLimitValueError(ValueError):
    def __init__(self) -> None:
        super().__init__("seer.rank.lookup_limits values must be non-negative")


class NewContentCategoryConfigError(ValueError):
    def __init__(self, unknown: list[str]) -> None:
        super().__init__(f"{NEW_CONTENT_CATEGORY_ERROR}: {', '.join(unknown)}")


def _coerce_sections(value: object) -> object:
    if value is None or value == "":
        return ["all"]

    return string_list(value)


def _normalize_sections(
    value: Iterable[str],
    allowed: tuple[str, ...],
    *,
    path: str,
) -> list[str]:
    normalized: list[str] = []
    unknown: list[str] = []

    for raw in value:
        section = str(raw).strip().lower()
        if not section:
            continue
        if section in {"*", "all"}:
            return list(allowed)
        if section not in allowed:
            unknown.append(section)
            continue
        if section not in normalized:
            normalized.append(section)

    if unknown:
        raise ValueError(  # noqa: TRY003
            f"{path} contains unknown section(s): {', '.join(unknown)}"
        )

    return normalized


def _validate_sqlite_path(value: Path) -> Path:
    if value.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        raise ValueError("cache path must use .sqlite, .sqlite3, or .db")  # noqa: TRY003

    return value


SQLitePath = Annotated[Path, AfterValidator(_validate_sqlite_path)]


def _normalize_int_mapping(value: object) -> object:
    if value is None:
        return {}
    if not isinstance(value, dict):
        return value
    return {str(key).strip(): int(number) for key, number in value.items()}


class PlayerBindingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_cooldown_days: int = Field(default=3, ge=0)


class PlayerQueryLimitsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    bound_default_daily_limit: int = Field(default=60, ge=0)
    bound_other_daily_limit: int = Field(default=60, ge=0)
    unbound_daily_limit: int = Field(default=30, ge=0)
    superuser_bypass: bool = True

    @model_validator(mode="before")
    @classmethod
    def _migrate_other_target_limit(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        legacy = value.get("other_target_action_daily_limit")
        if legacy is None or "bound_other_daily_limit" in value:
            return value
        return {
            key: item
            for key, item in value.items()
            if key != "other_target_action_daily_limit"
        } | {"bound_other_daily_limit": legacy}


class PlayerRequestProtectionConfig(BaseModel):
    """Serialize live player lookups and pause briefly after disconnects."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_queued_queries: int = Field(default=3, ge=0)
    base_request_interval_seconds: float = Field(default=1.2, ge=0)
    disconnect_pause_seconds: float = Field(default=60.0, ge=0)
    repeat_disconnect_window_seconds: float = Field(default=600.0, ge=0)
    repeat_disconnect_pause_seconds: float = Field(default=300.0, ge=0)
    superuser_priority: bool = True
    superuser_bypass_pause: bool = True


class PlayerBackgroundRefreshConfig(BaseModel):
    """Optional prefetch after a successful player lookup."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    cache_ttl_seconds: float = Field(default=300.0, gt=0)


class PlayerQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=30, gt=0)
    detail_timeout_seconds: float = Field(default=90, gt=0)
    sections: list[str] = Field(default_factory=lambda: list(PLAYER_SECTION_KEYS))
    binding: PlayerBindingConfig = Field(default_factory=PlayerBindingConfig)
    query_limits: PlayerQueryLimitsConfig = Field(
        default_factory=PlayerQueryLimitsConfig
    )
    request_protection: PlayerRequestProtectionConfig = Field(
        default_factory=PlayerRequestProtectionConfig
    )
    background_refresh: PlayerBackgroundRefreshConfig = Field(
        default_factory=PlayerBackgroundRefreshConfig
    )

    @field_validator("sections", mode="before")
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(
            value,
            PLAYER_SECTION_KEYS,
            path="seer.player.sections",
        )


class TeamQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timeout_seconds: float = Field(default=20, gt=0)
    sections: list[str] = Field(default_factory=lambda: ["basic", "resource"])

    @field_validator("sections", mode="before")
    @classmethod
    def coerce_sections(cls, value: object) -> object:
        return _coerce_sections(value)

    @field_validator("sections")
    @classmethod
    def normalize_sections(cls, value: list[str]) -> list[str]:
        return _normalize_sections(
            value,
            TEAM_SECTION_KEYS,
            path="seer.team.sections",
        )


class MintmarkQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    merge_connected: bool = True


class RankPageRefreshConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    target_limit: int = Field(default=50000, ge=1)
    target_limits: dict[str, int] = Field(default_factory=dict)
    score_cutoffs: dict[str, int] = Field(
        default_factory=lambda: {"群星牌": 1000},
    )
    stale_age_weight: float = Field(default=0.08, ge=0)
    stale_age_max_multiplier: float = Field(default=5.0, ge=1)
    page_size: int = Field(default=100, ge=1)
    pages_per_run: int = Field(default=10, ge=1)
    pages_per_run_min: int = Field(default=0, ge=0)
    interval_minutes: int = Field(default=0, ge=0, le=59)
    interval_offset_minutes: int = Field(default=0, ge=0, le=59)
    interval_offset_seconds: int = Field(default=0, ge=0, le=59)
    schedule_jitter_seconds: int = Field(default=0, ge=0)
    request_interval_seconds: float = Field(default=0.0, ge=0)
    request_jitter_seconds: float = Field(default=0.0, ge=0)
    active_start: str = ""
    active_end: str = ""
    times: list[str] = Field(
        default_factory=lambda: list(DEFAULT_RANK_PAGE_REFRESH_TIMES)
    )
    rank_keys: NormalizedStringList = Field(
        default_factory=lambda: list(DEFAULT_RANK_PAGE_REFRESH_KEYS)
    )
    refresh_stale_after_hours: int = Field(default=24, ge=0)

    @field_validator("times", mode="before")
    @classmethod
    def normalize_times(cls, value: object) -> object:
        return normalized_daily_times(
            value,
            error_message=RANK_PAGE_REFRESH_TIME_ERROR,
        )

    @field_validator("active_start", "active_end", mode="before")
    @classmethod
    def normalize_active_time(cls, value: object) -> str:
        if value is None:
            return ""
        text = str(value).strip()
        if not text:
            return ""
        return normalized_daily_times(
            [text],
            error_message=RANK_PAGE_REFRESH_ACTIVE_TIME_ERROR,
        )[0]

    @field_validator("target_limits", mode="before")
    @classmethod
    def normalize_target_limits(cls, value: object) -> object:
        return _normalize_int_mapping(value)

    @field_validator("target_limits")
    @classmethod
    def validate_target_limits(cls, value: dict[str, int]) -> dict[str, int]:
        return {key: limit for key, limit in value.items() if key and limit >= 1}

    @field_validator("score_cutoffs", mode="before")
    @classmethod
    def normalize_score_cutoffs(cls, value: object) -> object:
        return _normalize_int_mapping(value)

    @field_validator("score_cutoffs")
    @classmethod
    def validate_score_cutoffs(cls, value: dict[str, int]) -> dict[str, int]:
        return {key: score for key, score in value.items() if key and score >= 1}

    @model_validator(mode="after")
    def validate_interval_offset(self) -> RankPageRefreshConfig:
        if (
            self.interval_minutes > 0
            and self.interval_offset_minutes >= self.interval_minutes
        ):
            raise ValueError(RANK_PAGE_REFRESH_INTERVAL_OFFSET_ERROR)
        if self.pages_per_run_min > self.pages_per_run:
            raise ValueError(RANK_PAGE_REFRESH_PAGES_PER_RUN_MIN_ERROR)
        if bool(self.active_start) != bool(self.active_end):
            raise ValueError(RANK_PAGE_REFRESH_ACTIVE_PAIR_ERROR)
        return self


class PlayerRankLookupConfig(BaseModel):
    """Bounded parallel scheduling for rank sections in player detail replies."""

    model_config = ConfigDict(extra="forbid")

    page_timeout_seconds: float = Field(default=8, gt=0)
    total_timeout_seconds: float = Field(default=60, gt=0)
    page_retry_count: int = Field(default=1, ge=0, le=3)

    @model_validator(mode="after")
    def validate_budget(self) -> "PlayerRankLookupConfig":
        if self.total_timeout_seconds < self.page_timeout_seconds:
            raise ValueError(PLAYER_RANK_LOOKUP_TIMEOUT_ERROR)
        return self


class RankExclusionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taomee_internal_user_ids: tuple[int, ...] = DEFAULT_TAOMEE_INTERNAL_USER_IDS
    user_ids_by_rank: dict[str, tuple[int, ...]] = Field(
        default_factory=lambda: {
            rank_key: tuple(user_ids)
            for rank_key, user_ids in DEFAULT_RANK_EXCLUSION_USER_IDS_BY_RANK.items()
        }
    )

    @field_validator("taomee_internal_user_ids", mode="after")
    @classmethod
    def normalize_taomee_ids(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        return _normalize_rank_exclusion_ids(value)

    @field_validator("user_ids_by_rank", mode="after")
    @classmethod
    def normalize_rank_ids(
        cls,
        value: dict[str, tuple[int, ...]],
    ) -> dict[str, tuple[int, ...]]:
        unknown = set(value).difference(RANK_EXCLUSION_SUPPORTED_KEYS)
        if unknown:
            raise RankExclusionRankKeyError(unknown)
        return {
            rank_key: _normalize_rank_exclusion_ids(user_ids)
            for rank_key, user_ids in value.items()
        }


def _normalize_rank_exclusion_ids(value: tuple[int, ...]) -> tuple[int, ...]:
    normalized = tuple(dict.fromkeys(int(user_id) for user_id in value))
    if any(user_id <= 0 for user_id in normalized):
        raise ValueError(RANK_EXCLUSION_USER_ID_ERROR)
    return normalized


class RankQueryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10000, ge=0)
    online_limit: int = Field(default=2000, ge=0)
    lookup_limits: dict[str, int] = Field(default_factory=dict)
    page_size: int = Field(default=100, ge=1)
    display_limit: int = Field(default=10, ge=1, le=MAX_RANK_DISPLAY_LIMIT)
    max_display_limit: int = Field(
        default=MAX_RANK_DISPLAY_LIMIT,
        ge=1,
        le=MAX_RANK_DISPLAY_LIMIT,
    )
    display_limits: dict[str, int] = Field(default_factory=dict)
    page_cache: bool = True
    page_cache_ttl_seconds: int = Field(default=3600, ge=0)
    allow_stale_cache: bool = True
    score_search_probe_limit: int = Field(default=32, ge=1)
    score_search_tie_page_limit: int = Field(default=5, ge=1)
    page_cache_path: SQLitePath = Path("data/seer/rank_page_cache.sqlite")
    peak_subkey: int | None = Field(default=None, ge=0)
    exclusions: RankExclusionConfig = Field(default_factory=RankExclusionConfig)
    player_lookup: PlayerRankLookupConfig = Field(
        default_factory=PlayerRankLookupConfig
    )
    page_refresh: RankPageRefreshConfig = Field(default_factory=RankPageRefreshConfig)

    @field_validator("peak_subkey", mode="before")
    @classmethod
    def empty_peak_subkey_as_none(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @field_validator("display_limits", mode="before")
    @classmethod
    def normalize_display_limits(cls, value: object) -> object:
        return _normalize_int_mapping(value)

    @field_validator("display_limits")
    @classmethod
    def validate_display_limits(cls, value: dict[str, int]) -> dict[str, int]:
        return {
            key: limit
            for key, limit in value.items()
            if key and 1 <= limit <= MAX_RANK_DISPLAY_LIMIT
        }

    @field_validator("lookup_limits", mode="before")
    @classmethod
    def normalize_lookup_limits(cls, value: object) -> object:
        return _normalize_int_mapping(value)

    @field_validator("lookup_limits")
    @classmethod
    def validate_lookup_limits(cls, value: dict[str, int]) -> dict[str, int]:
        unknown = set(value).difference(DEFAULT_RANK_PAGE_REFRESH_KEYS)
        if unknown:
            raise RankLookupLimitRankKeyError(unknown)
        if any(limit < 0 for limit in value.values()):
            raise RankLookupLimitValueError
        return {key: limit for key, limit in value.items() if key}

    @model_validator(mode="after")
    def validate_display_limit_bounds(self) -> "RankQueryConfig":
        self.display_limit = min(self.display_limit, self.max_display_limit)
        self.display_limits = {
            key: min(limit, self.max_display_limit)
            for key, limit in self.display_limits.items()
        }
        return self


class LocalRankConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    max_players: int = Field(default=5000, ge=1)
    batch_limit: int = Field(default=100, ge=1)
    auto_refresh: bool = True
    time: str = "03:30:00"
    refresh_limit: int = Field(default=300, ge=1)
    refresh_max_age_hours: int = Field(default=24, ge=0)
    refresh_interval_seconds: float = Field(default=0.5, ge=0)
    path: SQLitePath = Path("data/seer/player_query_cache.sqlite")

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_time_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        legacy_hour = data.pop("refresh_hour", None)
        legacy_minute = data.pop("refresh_minute", None)
        if data.get("time") is not None or legacy_hour is None:
            return data

        try:
            hour = int(legacy_hour)
            minute = int(legacy_minute) if legacy_minute is not None else 0
        except (TypeError, ValueError) as exc:
            raise ValueError(LOCAL_RANK_REFRESH_TIME_ERROR) from exc
        data["time"] = f"{hour:02d}:{minute:02d}"
        return data

    @field_validator("time")
    @classmethod
    def normalize_time(cls, value: str) -> str:
        return normalize_daily_time(value, error_message=LOCAL_RANK_REFRESH_TIME_ERROR)


class TeamResourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    times: list[str] = Field(default_factory=list)
    commands: NormalizedStringList = Field(default_factory=lambda: ["战队"])
    default_threshold: int = Field(default=1000, ge=0)
    default_at_users: OneBotReferenceList = Field(default_factory=list)
    query_timeout_seconds: int = Field(default=20, gt=0)
    resource_line: str = (
        "查到了战队 {team_name}（{team_id}）资源是 {resource}，低于阈值 {threshold}。"
    )
    resource_message: str = "出来买资源，别逼我求你😡"

    @field_validator("times", mode="before")
    @classmethod
    def normalize_times(cls, value: object) -> object:
        return normalized_daily_times(value, error_message=TEAM_RESOURCE_TIME_ERROR)


class RenderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cache_max_size_mb: int = Field(default=200, gt=0)


class SeasonCountdownConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    autocard_name: str = "群星牌赛季"
    autocard_start_time: object | None = None
    autocard_end_time: object | None = None

    @field_validator("autocard_start_time", "autocard_end_time", mode="before")
    @classmethod
    def empty_time_as_none(cls, value: object) -> object:
        if value is None or value == "":
            return None
        from datetime import datetime

        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        raise ValueError("season time must be an ISO datetime")  # noqa: TRY003


class PlayerAccountConfig(BaseModel):
    """Named Seer account available to headless services and scoped aliases."""

    model_config = ConfigDict(extra="forbid")

    player_id: int = Field(ge=PLAYER_ID_MIN, le=PLAYER_ID_MAX)
    name: str
    aliases: list[str] = Field(default_factory=list)
    public: bool = False
    password: str | None = Field(default=None, exclude=True, repr=False)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError(PLAYER_ACCOUNT_NAME_ERROR)
        return normalized

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: list[str]) -> list[str]:
        return _normalize_player_account_aliases(
            value,
            error=PLAYER_ACCOUNT_ALIASES_ERROR,
        )

def _normalize_player_account_aliases(
    value: list[str],
    *,
    error: str,
) -> list[str]:
    normalized = [str(alias).strip() for alias in value]
    if any(not alias for alias in normalized):
        raise ValueError(error)
    return list(dict.fromkeys(normalized))


class ExternalReferencesConfig(BaseModel):
    """Optional SeerInfo companion links for matching query replies."""

    model_config = ConfigDict(extra="forbid")

    player_query: StrictBool = True
    team_query: StrictBool = True
    server_status: StrictBool = True
    weekly_preview: StrictBool = True
    bilibili_history: StrictBool = True
    peak_pool: StrictBool = True
    peak_vote: StrictBool = True
    peak_player_rank: StrictBool = True
    peak_suit_rank: StrictBool = True
    peak_title_rank: StrictBool = True
    peak_pet_rank: StrictBool = True


class NewContentConfig(BaseModel):
    """Control which weekly-content categories expand on the root menu."""

    model_config = ConfigDict(extra="forbid")

    expanded_categories: list[NewContentCategoryKey] = Field(default_factory=list)
    auto_expand_max_items: int = Field(default=5, ge=0)

    @field_validator("expanded_categories", mode="before")
    @classmethod
    def validate_expanded_categories(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        unknown = [
            str(category)
            for category in value
            if category not in NEW_CONTENT_CATEGORY_KEYS
        ]
        if unknown:
            raise NewContentCategoryConfigError(unknown)
        return value

    @field_validator("expanded_categories")
    @classmethod
    def deduplicate_expanded_categories(
        cls,
        value: list[NewContentCategoryKey],
    ) -> list[NewContentCategoryKey]:
        return list(dict.fromkeys(value))


class SeerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    player_accounts: list[PlayerAccountConfig] = Field(default_factory=list)
    player_account_aliases: dict[str, list[str]] = Field(default_factory=dict)
    player: PlayerQueryConfig = Field(default_factory=PlayerQueryConfig)
    team: TeamQueryConfig = Field(default_factory=TeamQueryConfig)
    mintmark: MintmarkQueryConfig = Field(default_factory=MintmarkQueryConfig)
    rank: RankQueryConfig = Field(default_factory=RankQueryConfig)
    local_rank: LocalRankConfig = Field(default_factory=LocalRankConfig)
    team_resource: TeamResourceConfig = Field(default_factory=TeamResourceConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    season: SeasonCountdownConfig = Field(default_factory=SeasonCountdownConfig)
    new_content: NewContentConfig = Field(default_factory=NewContentConfig)
    external_references: ExternalReferencesConfig = Field(
        default_factory=ExternalReferencesConfig
    )
    lucky_skin_window: LuckySkinWindowConfig = Field(
        default_factory=LuckySkinWindowConfig
    )

    @model_validator(mode="before")
    @classmethod
    def reject_unknown_external_references(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        references = value.get("external_references")
        if not isinstance(references, dict):
            return value
        unknown = set(references).difference(ExternalReferencesConfig.model_fields)
        if unknown:
            message = ", ".join(sorted(str(key) for key in unknown))
            raise ValueError(
                "seer.external_references contains unknown key(s): " + message
            )
        return value
