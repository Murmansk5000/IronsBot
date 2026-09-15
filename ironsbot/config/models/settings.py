# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Literal

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
from ironsbot.config.models.features import FeatureConfig, validate_feature_config
from ironsbot.config.models.messaging import MessageConfig
from ironsbot.config.models.operations import OperationsConfig
from ironsbot.config.models.pet_config import PetConfigConfig
from ironsbot.config.models.seer import SeerConfig
from ironsbot.config.onebot_references import (
    OneBotReferenceList,
    OneBotReferenceResolver,
)
from ironsbot.config.platform_references import (
    PlatformReferenceResolver,
    build_platform_reference_resolver,
)
from ironsbot.core.bilibili import BiliConfig
from ironsbot.core.commands import csv_items, json_array
from ironsbot.core.features import FEATURE_KEYS
from ironsbot.core.promotions import PromotionCatalog, PromotionConfig
from ironsbot.services.identity.player_accounts import (
    PlayerAccount,
    PlayerAccountRegistry,
    build_player_account_registry,
)

if TYPE_CHECKING:
    from ironsbot.core.platform import ConversationRef

VALID_LOG_LEVELS = {
    "TRACE",
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
}
_QQ_OFFICIAL_TEAM_RESOURCE_PROACTIVE_ERROR = (
    "proactive_messages must be true when "
    "team_resource_subscription is enabled"
)
_QQ_OFFICIAL_ACCOUNT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


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
            f"{location} requires environment variable SEER_PASSWORD_{player_id}"
        )


class QQOfficialConfigError(ValueError):
    @classmethod
    def no_enabled_accounts(cls) -> QQOfficialConfigError:
        return cls("bot.qq_official requires at least one enabled account")

    @classmethod
    def invalid_account_name(cls) -> QQOfficialConfigError:
        return cls(
            "bot.qq_official account names must match [A-Za-z][A-Za-z0-9_]*"
        )

    @classmethod
    def duplicate_app_id(cls, app_id: str) -> QQOfficialConfigError:
        return cls(f"duplicate QQ Official AppID: {app_id}")

    @classmethod
    def duplicate_secret_environment(cls, name: str) -> QQOfficialConfigError:
        return cls(
            "QQ Official account aliases must be unique ignoring case; "
            f"duplicate environment suffix: {name.upper()}"
        )

    @classmethod
    def invalid_target_policy(cls) -> QQOfficialConfigError:
        return cls("QQ Official target policy must be a table")

    @classmethod
    def empty_target_openid(cls) -> QQOfficialConfigError:
        return cls("QQ Official target OpenID must not be empty")

    @classmethod
    def invalid_alias_mapping(cls) -> QQOfficialConfigError:
        return cls("QQ Official target aliases must be a table")

    @classmethod
    def empty_target_alias(cls) -> QQOfficialConfigError:
        return cls("QQ Official target alias must not be empty or numeric")


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
    server_status: int = Field(default=1, ge=0)
    server_status_admin: int = Field(default=2, ge=0)
    bilibili: int = Field(default=3, ge=0)
    sendpic: int = Field(default=4, ge=0)
    red_packet_notice: int = Field(default=5, ge=0)
    seer_player: int = Field(default=10, ge=0)
    seer_team: int = Field(default=11, ge=0)
    seer_rank: int = Field(default=12, ge=0)
    seer_rank_help: int = Field(default=13, ge=0)
    seer_autocard: int = Field(default=14, ge=0)
    lucky_skin_window: int = Field(default=15, ge=0)
    seer_type: int = Field(default=20, ge=0)
    seer_equipment: int = Field(default=21, ge=0)
    seer_peak: int = Field(default=22, ge=0)
    seer_data: int = Field(default=23, ge=0)
    team_resource_subscription: int = Field(default=24, ge=0)
    help: int = Field(default=30, ge=0)
    about: int = Field(default=31, ge=0)
    message_commands: int = Field(default=40, ge=0)
    ai_intent: int = Field(default=50, ge=0)
    meeting: int = Field(default=60, ge=0)
    activity: int = Field(default=70, ge=0)
    db_sync: int = Field(default=80, ge=0)
    team_audit: int = Field(default=90, ge=0)
    seer_mintmark: int = Field(default=100, ge=0)
    pet_config: int = Field(default=109, ge=0)
    seer_pet: int = Field(default=110, ge=0)
    seer_query: int = Field(default=120, ge=0)
    ai_chat: int = Field(default=200, ge=0)


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_enabled: bool = False
    file_level: str = "INFO"
    error_file_enabled: bool = False
    rotation: str = "00:00"
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

    @field_validator("rotation", "retention")
    @classmethod
    def normalize_required_strings(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "bot.logging fields must not be empty"
            raise ValueError(msg)
        return normalized

    @field_validator("compression", mode="before")
    @classmethod
    def normalize_optional_string(cls, value: object) -> object:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None


class QQOfficialAccountConfig(BaseModel):
    """One independently authenticated QQ Official Bot account."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    required: bool = False
    app_id: str = ""
    secret: str = Field(default="", exclude=True, repr=False)
    proactive_messages: bool = False
    custom_keyboards: bool = False
    features: list[str] = Field(
        default_factory=lambda: [
            "help",
            "about",
            "seer_data",
            "seer_player",
            "seer_team",
            "seer_pet",
            "seer_mintmark",
            "seer_equipment",
            "seer_type",
            "seer_peak",
            "seer_rank",
        ]
    )
    superusers: list[str] = Field(default_factory=list)
    group_superusers: dict[str, list[str]] = Field(default_factory=dict)
    group_aliases: dict[str, str] = Field(default_factory=dict)
    user_aliases: dict[str, str] = Field(default_factory=dict)
    group_member_aliases: dict[str, dict[str, str]] = Field(default_factory=dict)
    group_policy: dict[str, list[str]] = Field(default_factory=dict)
    user_policy: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("app_id", "secret", mode="before")
    @classmethod
    def normalize_credentials(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("features", "superusers", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> list[str]:
        return _command_starts(value)

    @field_validator("group_aliases", "user_aliases", mode="before")
    @classmethod
    def normalize_target_aliases(cls, value: object) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise QQOfficialConfigError.invalid_alias_mapping()
        aliases: dict[str, str] = {}
        for raw_alias, raw_openid in value.items():
            alias = str(raw_alias).strip()
            if not alias or alias.isdecimal():
                raise QQOfficialConfigError.empty_target_alias()
            openid = str(raw_openid).strip()
            if not openid:
                raise QQOfficialConfigError.empty_target_openid()
            aliases[alias] = openid
        return aliases

    def resolve_group_openid(self, reference: str) -> str:
        return self.group_aliases.get(reference, reference)

    def resolve_user_openid(self, reference: str) -> str:
        return self.user_aliases.get(reference, reference)

    def resolve_group_member_openid(
        self,
        group_reference: str,
        member_reference: str,
    ) -> str:
        return self.group_member_aliases.get(group_reference, {}).get(
            member_reference,
            member_reference,
        )

    @field_validator("group_member_aliases", mode="before")
    @classmethod
    def normalize_group_member_aliases(
        cls,
        value: object,
    ) -> dict[str, dict[str, str]]:
        if not isinstance(value, Mapping):
            raise QQOfficialConfigError.invalid_alias_mapping()
        groups: dict[str, dict[str, str]] = {}
        for raw_group, raw_aliases in value.items():
            group = str(raw_group).strip()
            if not group:
                raise QQOfficialConfigError.empty_target_openid()
            groups[group] = cls.normalize_target_aliases(raw_aliases)
        return groups

    @field_validator("group_policy", "user_policy", mode="before")
    @classmethod
    def normalize_target_policy(cls, value: object) -> dict[str, list[str]]:
        if not isinstance(value, Mapping):
            raise QQOfficialConfigError.invalid_target_policy()
        policy: dict[str, list[str]] = {}
        for raw_target, raw_features in value.items():
            target = str(raw_target).strip()
            if not target:
                raise QQOfficialConfigError.empty_target_openid()
            policy[target] = _command_starts(raw_features)
        return policy

    @field_validator("group_superusers", mode="before")
    @classmethod
    def normalize_group_superusers(cls, value: object) -> dict[str, list[str]]:
        if not isinstance(value, Mapping):
            raise QQOfficialConfigError.invalid_target_policy()
        result: dict[str, list[str]] = {}
        for raw_group, raw_members in value.items():
            group = str(raw_group).strip()
            if not group:
                raise QQOfficialConfigError.empty_target_openid()
            members = _command_starts(raw_members)
            if not members:
                raise ValueError(  # noqa: TRY003
                    "QQ Official group superusers must not be empty"
                )
            result[group] = members
        return result

    @property
    def configured_features(self) -> set[str]:
        return {
            *self.features,
            *(
                feature
                for policy in (self.group_policy, self.user_policy)
                for features in policy.values()
                for feature in features
            ),
        }


class QQOfficialConfig(BaseModel):
    """QQ Official transport and independently scoped bot accounts."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    sandbox: bool = False
    startup_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    accounts: dict[str, QQOfficialAccountConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_accounts(self) -> QQOfficialConfig:
        enabled_accounts = self.enabled_accounts
        if self.enabled and not enabled_accounts:
            raise QQOfficialConfigError.no_enabled_accounts()
        app_ids: set[str] = set()
        environment_names: set[str] = set()
        for name, account in self.accounts.items():
            if not _QQ_OFFICIAL_ACCOUNT_NAME.fullmatch(name):
                raise QQOfficialConfigError.invalid_account_name()
            environment_name = name.upper()
            if environment_name in environment_names:
                raise QQOfficialConfigError.duplicate_secret_environment(name)
            environment_names.add(environment_name)
            if not self.enabled or not account.enabled:
                continue
            missing = [
                field
                for field, value in (
                    ("app_id", account.app_id),
                    ("secret", account.secret),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    f"bot.qq_official.accounts.{name} requires "
                    + ", ".join(missing)
                    + " when enabled"
                )
            if account.app_id in app_ids:
                raise QQOfficialConfigError.duplicate_app_id(account.app_id)
            app_ids.add(account.app_id)
            if (
                "team_resource_subscription" in account.configured_features
                and not account.proactive_messages
            ):
                raise ValueError(
                    f"bot.qq_official.accounts.{name}."
                    + _QQ_OFFICIAL_TEAM_RESOURCE_PROACTIVE_ERROR
                )
        return self

    @property
    def enabled_accounts(self) -> dict[str, QQOfficialAccountConfig]:
        if not self.enabled:
            return {}
        return {
            name: account
            for name, account in self.accounts.items()
            if account.enabled
        }


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str = "prod"
    driver: str = "~fastapi+~httpx"
    host: str = "0.0.0.0"  # nosec B104
    port: int = Field(default=8080, gt=0)
    log_level: str = "INFO"
    command_start: list[str] = Field(default_factory=lambda: ["/", ""])
    plugin_manifest: Literal["full", "core"] = "full"
    superusers: OneBotReferenceList = Field(default_factory=list)
    onebot_token: str = Field(default="", exclude=True, repr=False)
    qq_official: QQOfficialConfig = Field(default_factory=QQOfficialConfig)
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


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot: BotConfig = Field(default_factory=BotConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    promotions: dict[str, PromotionConfig] = Field(default_factory=dict)
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
                qq_official=self.bot.qq_official,
            )
            self._validate_onebot_references()
            self._validate_promotions()
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

    def _validate_promotions(self) -> None:
        catalog = PromotionCatalog(self.promotions)
        for promotion_id, promotion in self.promotions.items():
            if not promotion_id.strip():
                raise ValueError("promotions contains an empty id")  # noqa: TRY003
            if promotion.feature not in FEATURE_KEYS:
                raise ValueError(  # noqa: TRY003
                    f"promotions.{promotion_id}.feature={promotion.feature} "
                    "is not registered"
                )
        for action_id, action in self.ai.intent_actions.items():
            if not action.enabled or action.action != "promotion":
                continue
            promotion = catalog.get(action.promotion)
            if promotion is None or not promotion.enabled:
                raise ValueError(  # noqa: TRY003
                    f"ai.intent_actions.{action_id}.promotion="
                    f"{action.promotion} is not an enabled promotion"
                )

    @property
    def onebot_references(self) -> OneBotReferenceResolver:
        return OneBotReferenceResolver(
            group_aliases=self.features.group_aliases,
            user_aliases=self.features.user_aliases,
        )

    @property
    def platform_references(self) -> PlatformReferenceResolver:
        return build_platform_reference_resolver(
            self.onebot_references,
            self.bot.qq_official.enabled_accounts.values(),
        )

    @property
    def player_accounts(self) -> PlayerAccountRegistry:
        groups: dict[ConversationRef, list[str]] = {}
        for group_ref, account_refs in self.seer.player_account_aliases.items():
            conversation = self.onebot_references.group_conversation_ref(
                group_ref,
                location=f"seer.player_account_aliases.{group_ref}",
            )
            groups.setdefault(conversation, []).extend(account_refs)
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
        platform_references = self.platform_references
        accounts = self.player_accounts
        _ = self.headless_accounts
        references.resolve_users(self.bot.superusers, location="bot.superusers")
        self._validate_policy_refs(
            self.features.group_policy,
            resolve=platform_references.group_conversation_refs,
            location="features.group_policy",
        )
        self._validate_policy_refs(
            self.features.user_policy,
            resolve=platform_references.actor_refs,
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
            resolve=platform_references.group_conversation_refs,
            location="bilibili.push.groups",
        )
        self._validate_mapping_refs(
            self.bilibili.push.users,
            resolve=platform_references.private_conversation_refs,
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
        for index, action in enumerate(self.messaging.schedules):
            references.resolve_users(
                action.at_user_ids,
                location=f"messaging.schedules[{index}].at_user_ids",
            )

    @staticmethod
    def _validate_mapping_refs(
        mapping: Mapping[str, object],
        *,
        resolve: Callable[..., object],
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
        resolve: Callable[..., object],
        location: str,
    ) -> None:
        for reference in policy:
            resolve(reference, location=f"{location}.{reference}")
