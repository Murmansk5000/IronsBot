# SPDX-License-Identifier: MIT
from __future__ import annotations

import logging
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
from ironsbot.config.models.identities import IdentityConfig
from ironsbot.config.models.messaging import MessageConfig
from ironsbot.config.models.operations import OperationsConfig
from ironsbot.config.models.pet_config import PetConfigConfig
from ironsbot.config.models.seer import SeerConfig
from ironsbot.config.models.transport import OneBotConfig
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
from ironsbot.core.platform_selection import OutboundPlatformSelection
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
    "proactive_messages must be true when team_resource_subscription is enabled"
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
    def invalid_account_name(cls) -> QQOfficialConfigError:
        return cls("bot.qq_official account names must match [A-Za-z][A-Za-z0-9_]*")

    @classmethod
    def duplicate_app_id(cls, app_id: str) -> QQOfficialConfigError:
        return cls(f"duplicate QQ Official AppID: {app_id}")

    @classmethod
    def missing_app_id(cls, name: str) -> QQOfficialConfigError:
        return cls(f"bot.qq_official.accounts.{name}.app_id is required")

    @classmethod
    def invalid_target_policy(cls) -> QQOfficialConfigError:
        return cls("QQ Official target policy must be a table")

    @classmethod
    def empty_target_openid(cls) -> QQOfficialConfigError:
        return cls("QQ Official target OpenID must not be empty")

    @classmethod
    def missing_default_account(cls) -> QQOfficialConfigError:
        return cls(
            "bot.qq_official.default_account is required when multiple "
            "official accounts are active"
        )

    @classmethod
    def inactive_default_account(cls) -> QQOfficialConfigError:
        return cls(
            "bot.qq_official.default_account must name an active official account"
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

    poke_reply: int = Field(default=0, ge=0)
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
    mention_reply: int = Field(default=190, ge=0)
    ai_chat: int = Field(default=200, ge=0)

    @model_validator(mode="after")
    def validate_mention_reply_order(self) -> MatcherPriorityConfig:
        if not self.seer_query < self.mention_reply < self.ai_chat:
            msg = (
                "bot.matcher_priority.mention_reply must run after seer_query "
                "and before ai_chat"
            )
            raise ValueError(msg)
        return self


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

    required: bool = False
    app_id: str = ""
    secret: str = Field(default="", exclude=True, repr=False)
    proactive_messages: bool = True
    custom_keyboards: bool = False
    features: list[str] = Field(default_factory=list)
    group_policy: dict[str, list[str]] = Field(default_factory=dict)
    user_policy: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("app_id", "secret", mode="before")
    @classmethod
    def normalize_credentials(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("features", mode="before")
    @classmethod
    def normalize_string_lists(cls, value: object) -> list[str]:
        return _command_starts(value)

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

    @property
    def configured_features(self) -> set[str]:
        return set()


class QQOfficialConfig(BaseModel):
    """QQ Official transport and independently scoped bot accounts."""

    model_config = ConfigDict(extra="forbid")

    sandbox: bool = False
    startup_timeout_seconds: float = Field(default=15.0, gt=0, le=120)
    default_account: str = ""
    group_routes: dict[str, str] = Field(default_factory=dict)
    private_routes: dict[str, str] = Field(default_factory=dict)
    accounts: dict[str, QQOfficialAccountConfig] = Field(default_factory=dict)

    @field_validator("default_account", mode="before")
    @classmethod
    def normalize_default_account(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("group_routes", "private_routes", mode="before")
    @classmethod
    def normalize_group_routes(cls, value: object) -> dict[str, str]:
        if not isinstance(value, Mapping):
            raise QQOfficialConfigError.invalid_target_policy()
        routes: dict[str, str] = {}
        for raw_group, raw_account in value.items():
            group = str(raw_group).strip()
            account = str(raw_account).strip()
            if not group or not account:
                raise QQOfficialConfigError.invalid_target_policy()
            routes[group] = account
        return routes

    @model_validator(mode="after")
    def validate_accounts(self) -> QQOfficialConfig:
        app_ids: set[str] = set()
        for name, account in self.accounts.items():
            for key in ("features", "group_policy", "user_policy"):
                if key in account.model_fields_set:
                    logging.getLogger(__name__).warning(
                        "bot.qq_official.accounts.%s.%s is retired and ignored; "
                        "use features.group_policy / features.user_policy",
                        name,
                        key,
                    )
            if not _QQ_OFFICIAL_ACCOUNT_NAME.fullmatch(name):
                raise QQOfficialConfigError.invalid_account_name()
            if not account.app_id:
                if not account.secret:
                    continue
                raise QQOfficialConfigError.missing_app_id(name)
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
        return {
            name: account
            for name, account in self.accounts.items()
            if account.app_id and account.secret
        }

    @property
    def resolved_default_account(self) -> str | None:
        enabled = self.enabled_accounts
        if self.default_account:
            return self.default_account
        if len(enabled) == 1:
            return next(iter(enabled))
        return None


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    environment: str = "prod"
    driver: str = "~fastapi+~httpx"
    host: str = "0.0.0.0"  # nosec B104
    port: int = Field(default=8080, gt=0)
    log_level: str = "INFO"
    command_start: list[str] = Field(default_factory=lambda: ["/", ""])
    plugin_manifest: Literal["full", "core"] = "full"
    use_default_for_unconfigured_groups: bool = False
    superusers: OneBotReferenceList = Field(default_factory=list)
    onebot_token: str = Field(default="", exclude=True, repr=False)
    onebot: OneBotConfig = Field(default_factory=OneBotConfig)
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
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    bot: BotConfig = Field(default_factory=BotConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    identities: IdentityConfig = Field(default_factory=IdentityConfig)
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
            self._validate_platform_selection()
            self._validate_identity_accounts()
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

    def _validate_identity_accounts(self) -> None:
        declared = set(self.bot.qq_official.accounts)
        referenced = {
            account
            for targets in (self.identities.groups, self.identities.users)
            for target in targets.values()
            for account in target.official
        }
        unknown = sorted(referenced - declared)
        if unknown:
            msg = "identities reference undeclared official accounts: " + ", ".join(
                unknown
            )
            raise ValueError(msg)
        active = set(self.bot.qq_official.enabled_accounts)
        default_account = self.bot.qq_official.resolved_default_account
        if len(active) > 1 and default_account is None:
            raise QQOfficialConfigError.missing_default_account()
        if active and default_account is not None and default_account not in active:
            raise QQOfficialConfigError.inactive_default_account()
        unknown_groups = sorted(
            set(self.bot.qq_official.group_routes) - set(self.identities.groups)
        )
        if unknown_groups:
            raise ValueError(
                "bot.qq_official.group_routes reference unknown groups: "
                + ", ".join(unknown_groups)
            )
        groups_without_qq = sorted(
            alias
            for alias in self.bot.qq_official.group_routes
            if self.identities.groups[alias].qq is None
        )
        if groups_without_qq:
            raise ValueError(
                "bot.qq_official.group_routes require groups with QQ IDs: "
                + ", ".join(groups_without_qq)
            )
        route_accounts = set(self.bot.qq_official.group_routes.values())
        unknown_route_accounts = sorted(route_accounts - declared)
        if unknown_route_accounts:
            raise ValueError(
                "bot.qq_official.group_routes reference undeclared accounts: "
                + ", ".join(unknown_route_accounts)
            )
        inactive_route_accounts = sorted(route_accounts - active) if active else []
        if inactive_route_accounts:
            raise ValueError(
                "bot.qq_official.group_routes reference inactive accounts: "
                + ", ".join(inactive_route_accounts)
            )
        self._validate_private_routes(declared, active)

    def _validate_private_routes(
        self, declared: set[str], active: set[str]
    ) -> None:
        unknown_users = sorted(
            set(self.bot.qq_official.private_routes) - set(self.identities.users)
        )
        if unknown_users:
            raise ValueError(
                "bot.qq_official.private_routes reference unknown users: "
                + ", ".join(unknown_users)
            )
        users_without_qq = sorted(
            alias
            for alias in self.bot.qq_official.private_routes
            if self.identities.users[alias].qq is None
        )
        if users_without_qq:
            raise ValueError(
                "bot.qq_official.private_routes require users with QQ IDs: "
                + ", ".join(users_without_qq)
            )
        private_accounts = set(self.bot.qq_official.private_routes.values())
        if unknown := sorted(private_accounts - declared):
            raise ValueError(
                "bot.qq_official.private_routes reference undeclared accounts: "
                + ", ".join(unknown)
            )
        if inactive := sorted(private_accounts - active):
            raise ValueError(
                "bot.qq_official.private_routes reference inactive accounts: "
                + ", ".join(inactive)
            )

    def _validate_platform_selection(self) -> None:
        onebot = self.bot.onebot
        active_accounts = self.bot.qq_official.enabled_accounts
        if onebot.identity_verification:
            if not onebot.enabled:
                msg = "bot.onebot.identity_verification requires bot.onebot.enabled"
                raise ValueError(msg)
            if not active_accounts:
                msg = (
                    "bot.onebot.identity_verification requires complete "
                    "QQ Official environment credentials"
                )
                raise ValueError(msg)
            trusted = set(onebot.trusted_official_bots)
            expected = set(active_accounts)
            if trusted != expected:
                missing = sorted(expected - trusted)
                unknown = sorted(trusted - expected)
                details = []
                if missing:
                    details.append("missing " + ", ".join(missing))
                if unknown:
                    details.append("unknown " + ", ".join(unknown))
                msg = (
                    "bot.onebot.trusted_official_bots must exactly match active "
                    "official accounts: " + "; ".join(details)
                )
                raise ValueError(msg)

    @property
    def outbound_platform_selection(self) -> OutboundPlatformSelection:
        return OutboundPlatformSelection.resolve(
            official_account_aliases=tuple(self.bot.qq_official.enabled_accounts),
            onebot_enabled=self.bot.onebot.enabled,
            onebot_send_messages=self.bot.onebot.send_messages,
        )

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
            group_aliases={
                alias: target.qq
                for alias, target in self.identities.groups.items()
                if target.qq is not None
            },
            user_aliases={
                alias: target.qq
                for alias, target in self.identities.users.items()
                if target.qq is not None
            },
        )

    @property
    def platform_references(self) -> PlatformReferenceResolver:
        return build_platform_reference_resolver(
            self.onebot_references,
            self.identities,
            self.bot.qq_official.enabled_accounts,
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
        self._validate_mention_reply_references(platform_references)
        for index, action in enumerate(self.messaging.schedules):
            references.resolve_users(
                action.at_user_ids,
                location=f"messaging.schedules[{index}].at_user_ids",
            )

    def _validate_mention_reply_references(
        self,
        platform_references: PlatformReferenceResolver,
    ) -> None:
        for index, action in enumerate(self.messaging.mention_replies):
            for user_index, user in enumerate(action.users):
                location = f"messaging.mention_replies[{index}].users[{user_index}]"
                if user not in self.identities.users:
                    msg = f"{location} references unknown identity user alias: {user}"
                    raise SettingsReferenceError(msg)
                platform_references.actor_refs(user, location=location)

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
