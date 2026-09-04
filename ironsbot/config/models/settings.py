# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_core import InitErrorDetails, PydanticCustomError

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.ai import AiConfig
from ironsbot.config.models.messaging import MessageConfig
from ironsbot.config.models.operations import OperationsConfig
from ironsbot.config.models.pet_config import PetConfigConfig
from ironsbot.config.models.seer import SeerConfig
from ironsbot.config.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
    build_player_account_registry,
)
from ironsbot.core.bilibili import BiliConfig
from ironsbot.core.commands import csv_items, json_array
from ironsbot.core.features import FeatureConfig, validate_feature_config
from ironsbot.core.onebot_references import (
    OneBotReferenceList,
    OneBotReferenceResolver,
)
from ironsbot.core.time import normalize_daily_time

VALID_LOG_LEVELS = {
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
}


class SettingsReferenceError(ValueError):
    @classmethod
    def duplicate_lucky_skin_window_user(cls) -> SettingsReferenceError:
        return cls("seer.lucky_skin_window.accounts must not repeat a user")

    @classmethod
    def duplicate_lucky_skin_window_account(cls) -> SettingsReferenceError:
        return cls("seer.lucky_skin_window.accounts must not repeat an account")

    @classmethod
    def missing_player_account_password(
        cls,
        player_id: int,
        *,
        location: str = "seer.player_accounts",
    ) -> SettingsReferenceError:
        return cls(
            f"{location} "
            f"requires environment variable SEER_PASSWORD_{player_id}"
        )


class MatcherPriorityConfigError(ValueError):
    @classmethod
    def mention_reply_order(cls) -> MatcherPriorityConfigError:
        return cls(
            "bot.matcher_priority.mention_reply must run before ai_group_at"
        )

    @classmethod
    def bot_mention_order(cls) -> MatcherPriorityConfigError:
        return cls("bot.matcher_priority.ai_group_at must run before bot_mention_block")


class RuntimeMenuConfigError(ValueError):
    @classmethod
    def root_timeout_exceeds_maximum(cls) -> RuntimeMenuConfigError:
        return cls(
            "runtime.menu.root_timeout_minutes must not exceed max_timeout_minutes"
        )


def _command_starts(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        raw_items: Iterable[object] = (
            json_array(text, name="command start")
            if text.startswith("[")
            else csv_items(text)
        )
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        raw_items = value
    else:
        return []

    result: list[str] = []
    for raw_item in raw_items:
        item = str(raw_item).strip()
        if item not in result:
            result.append(item)
    return result


class MatcherPriorityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    help_hint: int = Field(default=0, ge=0)
    mention_reply: int = Field(default=-21, ge=-100)
    ai_group_at: int = Field(default=-20, ge=-100)
    bot_mention_block: int = Field(default=-19, ge=-100)
    server_status: int = Field(default=10, ge=0)
    server_status_admin: int = Field(default=11, ge=0)
    bilibili: int = Field(default=20, ge=0)
    sendpic: int = Field(default=30, ge=0)
    red_packet_notice: int = Field(default=40, ge=0)
    seer_player: int = Field(default=50, ge=0)
    seer_team: int = Field(default=51, ge=0)
    seer_rank: int = Field(default=52, ge=0)
    seer_rank_help: int = Field(default=53, ge=0)
    seer_autocard: int = Field(default=54, ge=0)
    lucky_skin_window: int = Field(default=55, ge=0)
    seer_type: int = Field(default=56, ge=0)
    seer_equipment: int = Field(default=57, ge=0)
    seer_peak: int = Field(default=58, ge=0)
    seer_data: int = Field(default=59, ge=0)
    team_resource_subscription: int = Field(default=60, ge=0)
    help: int = Field(default=70, ge=0)
    about: int = Field(default=71, ge=0)
    message_commands: int = Field(default=80, ge=0)
    ai_intent: int = Field(default=81, ge=0)
    meeting: int = Field(default=82, ge=0)
    activity: int = Field(default=83, ge=0)
    db_sync: int = Field(default=84, ge=0)
    team_audit: int = Field(default=85, ge=0)
    seer_mintmark: int = Field(default=90, ge=0)
    pet_config: int = Field(default=91, ge=0)
    seer_pet: int = Field(default=92, ge=0)
    seer_query: int = Field(default=93, ge=0)
    ai_chat: int = Field(default=100, ge=0)

    @model_validator(mode="after")
    def validate_bot_mention_order(self) -> MatcherPriorityConfig:
        if self.mention_reply >= self.ai_group_at:
            raise MatcherPriorityConfigError.mention_reply_order()
        if self.ai_group_at >= self.bot_mention_block:
            raise MatcherPriorityConfigError.bot_mention_order()
        return self


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_enabled: bool = False
    file_level: str = "INFO"
    error_file_enabled: bool = False
    rotation: str = "00:00:00"
    retention: str = "30 days"
    compression: str | None = None

    @field_validator("file_level")
    @classmethod
    def normalize_file_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in VALID_LOG_LEVELS:
            msg = f"bot.logging.file_level must be one of {sorted(VALID_LOG_LEVELS)}"
            raise ValueError(msg)
        return level

    @field_validator("retention")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "bot.logging fields must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("rotation")
    @classmethod
    def normalize_rotation(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "bot.logging.rotation must not be empty"
            raise ValueError(msg)
        if re.fullmatch(r"\d{1,2}:\d{1,2}(?::\d{1,2})?", normalized):
            return normalize_daily_time(
                normalized,
                error_message="bot.logging.rotation clock time must use HH:MM:SS",
            )
        return normalized

    @field_validator("compression", mode="before")
    @classmethod
    def normalize_optional_string(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str = "prod"
    driver: str = "~fastapi+~httpx"
    host: str = "0.0.0.0"  # nosec B104
    port: int = Field(default=8080, gt=0)
    log_level: str = "INFO"
    command_start: list[str] = Field(default_factory=lambda: ["/", ""])
    superusers: OneBotReferenceList = Field(default_factory=list)
    onebot_token: str = Field(default="", exclude=True, repr=False)
    matcher_priority: MatcherPriorityConfig = Field(
        default_factory=MatcherPriorityConfig
    )
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @field_validator("environment", "driver", "host")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "bot string fields must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in VALID_LOG_LEVELS:
            msg = f"bot.log_level must be one of {sorted(VALID_LOG_LEVELS)}"
            raise ValueError(msg)
        return normalized

    @field_validator("command_start", mode="before")
    @classmethod
    def normalize_command_start(cls, value: object) -> object:
        return _command_starts(value)


class PathsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    log_file: Path = Path("logs/ironsbot.log")
    error_log_file: Path = Path("logs/ironsbot.error.log")
    cache_root: Path = Path("cache")
    qq_state: Path = Path("data/state/qq_state.sqlite")
    runtime_state: Path = Path("data/state/runtime_state.sqlite")


class RuntimeConcurrencyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    render_max_concurrent: int = Field(default=1, ge=1, le=4)


class RuntimeSchedulerConfig(BaseModel):
    """Wall-clock policy shared by all first-party recurring jobs."""

    model_config = ConfigDict(extra="forbid")

    timezone: str = "Asia/Shanghai"
    clock_check_on_startup: bool = True
    clock_warning_threshold_seconds: float = Field(default=3.0, ge=0)
    clock_check_timeout_seconds: float = Field(default=3.0, gt=0)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            msg = f"runtime.scheduler.timezone is invalid: {value}"
            raise ValueError(msg) from exc
        return value


class RuntimeMenuConfig(BaseModel):
    """Lifetime policy for interactive multi-level menus, in minutes."""

    model_config = ConfigDict(extra="forbid")

    root_timeout_minutes: int = Field(default=3, ge=1)
    page_extension_minutes: int = Field(default=1, ge=1)
    max_timeout_minutes: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def validate_timeouts(self) -> RuntimeMenuConfig:
        if self.root_timeout_minutes > self.max_timeout_minutes:
            raise RuntimeMenuConfigError.root_timeout_exceeds_maximum()
        return self


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    concurrency: RuntimeConcurrencyConfig = Field(
        default_factory=RuntimeConcurrencyConfig
    )
    scheduler: RuntimeSchedulerConfig = Field(
        default_factory=RuntimeSchedulerConfig
    )
    menu: RuntimeMenuConfig = Field(default_factory=RuntimeMenuConfig)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot: BotConfig = Field(default_factory=BotConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    activity: ActivityConfig = Field(default_factory=ActivityConfig)
    bilibili: BiliConfig = Field(default_factory=BiliConfig)
    messaging: MessageConfig = Field(default_factory=MessageConfig)
    pet_config: PetConfigConfig = Field(default_factory=PetConfigConfig)
    seer: SeerConfig = Field(default_factory=SeerConfig)
    operations: OperationsConfig = Field(default_factory=OperationsConfig)

    @model_validator(mode="after")
    def validate_registered_features(self) -> Settings:
        try:
            validate_feature_config(
                self.features,
                command_features=self.messaging.command_feature_keys,
                schedule_features=self.messaging.schedule_feature_keys,
            )
            self._validate_onebot_references()
        except ValueError as exc:
            raise ValidationError.from_exception_data(
                self.__class__.__name__,
                [
                    InitErrorDetails(
                        type=PydanticCustomError(
                            "feature_config",
                            "{message}",
                            {"message": str(exc)},
                        ),
                        loc=("features",),
                        input=self.features.model_dump(),
                    )
                ],
            ) from exc
        return self

    @property
    def onebot_references(self) -> OneBotReferenceResolver:
        return OneBotReferenceResolver(
            group_aliases=self.features.group_aliases,
            user_aliases=self.features.user_aliases,
        )

    @property
    def player_accounts(self) -> PlayerAccountRegistry:
        groups: dict[int, list[str]] = {}
        for group_ref, account_refs in self.seer.player_account_aliases.items():
            group_id = self.onebot_references.resolve_group(
                group_ref,
                location=f"seer.player_account_aliases.{group_ref}",
            )
            groups.setdefault(group_id, []).extend(account_refs)
        return build_player_account_registry(
            self.seer.player_accounts,
            private_alias_groups=groups,
        )

    @property
    def headless_accounts(self) -> tuple[PlayerAccount, ...]:
        accounts = self.player_accounts
        resolved: list[PlayerAccount] = []
        seen: set[int] = set()
        for index, reference in enumerate(self.operations.headless.accounts):
            location = f"operations.headless.accounts[{index}]"
            account = accounts.resolve(reference, location=location)
            if account.player_id in seen:
                continue
            if account.password is None:
                raise SettingsReferenceError.missing_player_account_password(
                    account.player_id,
                    location=location,
                )
            seen.add(account.player_id)
            resolved.append(account)
        return tuple(resolved)

    @property
    def superuser_ids(self) -> frozenset[int]:
        return frozenset(
            self.onebot_references.resolve_users(
                self.bot.superusers,
                location="bot.superusers",
            )
        )

    def _validate_onebot_references(self) -> None:
        references = self.onebot_references
        accounts = self.player_accounts
        _ = self.headless_accounts
        references.resolve_users(self.bot.superusers, location="bot.superusers")
        self._validate_policy_refs(
            self.features.group_policy,
            resolve=references.resolve_group,
            location="features.group_policy",
        )
        self._validate_policy_refs(
            self.features.user_policy,
            resolve=references.resolve_user,
            location="features.user_policy",
        )
        self._validate_mapping_refs(
            self.features.help.poke_replies,
            resolve=references.resolve_group,
            location="features.help.poke_replies",
        )
        self._validate_mapping_refs(
            self.features.help.poke_user_replies,
            resolve=references.resolve_user,
            location="features.help.poke_user_replies",
        )
        self._validate_mapping_refs(
            self.bilibili.push.groups,
            resolve=references.resolve_group,
            location="bilibili.push.groups",
        )
        self._validate_mapping_refs(
            self.bilibili.push.users,
            resolve=references.resolve_user,
            location="bilibili.push.users",
        )
        lucky_users: set[int] = set()
        lucky_accounts: set[int] = set()
        for index, account in enumerate(self.seer.lucky_skin_window.accounts):
            user_id = references.resolve_user(
                account.user,
                location=f"seer.lucky_skin_window.accounts[{index}].user",
            )
            if user_id in lucky_users:
                raise SettingsReferenceError.duplicate_lucky_skin_window_user()
            lucky_users.add(user_id)
            configured_account = accounts.resolve(
                account.account,
                location=f"seer.lucky_skin_window.accounts[{index}].account",
            )
            if configured_account.player_id in lucky_accounts:
                raise SettingsReferenceError.duplicate_lucky_skin_window_account()
            lucky_accounts.add(configured_account.player_id)
            if (
                self.seer.lucky_skin_window.enabled
                and configured_account.password is None
            ):
                raise SettingsReferenceError.missing_player_account_password(
                    configured_account.player_id
                )
        self._validate_mapping_refs(
            self.messaging.bot_routing.groups,
            resolve=references.resolve_group,
            location="messaging.bot_routing.groups",
        )
        self._validate_mapping_refs(
            self.messaging.bot_routing.users,
            resolve=references.resolve_user,
            location="messaging.bot_routing.users",
        )
        self._validate_mapping_refs(
            self.seer.rank.display_limits,
            resolve=references.resolve_group,
            location="seer.rank.display_limits",
        )
        references.resolve_users(
            self.seer.team_resource.default_at_users,
            location="seer.team_resource.default_at_users",
        )
        for index, action in enumerate(self.messaging.commands):
            references.resolve_users(
                action.at_user_ids,
                location=f"messaging.commands[{index}].at_user_ids",
            )
        for index, action in enumerate(self.messaging.keyword_replies):
            references.resolve_users(
                action.at_user_ids,
                location=f"messaging.keyword_replies[{index}].at_user_ids",
            )
        for index, action in enumerate(self.messaging.mention_replies):
            references.resolve_users(
                action.user_ids,
                location=f"messaging.mention_replies[{index}].user_ids",
            )
        for index, action in enumerate(self.messaging.schedules):
            references.resolve_users(
                action.at_user_ids,
                location=f"messaging.schedules[{index}].at_user_ids",
            )

    @staticmethod
    def _validate_mapping_refs(
        mapping: Mapping[str, object],
        *,
        resolve: Callable[..., int],
        location: str,
    ) -> None:
        Settings._validate_policy_refs(
            {key: [] for key in mapping},
            resolve=resolve,
            location=location,
        )

    @staticmethod
    def _validate_policy_refs(
        policy: Mapping[str, object],
        *,
        resolve: Callable[..., int],
        location: str,
    ) -> None:
        for reference in policy:
            resolve(reference, location=f"{location}.{reference}")
