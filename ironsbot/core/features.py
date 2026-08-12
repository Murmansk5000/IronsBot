# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import Enum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.core.commands import (
    NormalizedStringList,
    csv_items,
    json_array,
    json_object,
    string_list,
    unique_items,
)
from ironsbot.core.onebot_references import (
    OneBotReferenceResolver,
    normalize_alias_mapping,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class Feature(str, Enum):
    ABOUT = "about"
    ADMIN_NOTICE = "admin_notice"
    AI_CHAT = "ai_chat"
    AI_INTENT = "ai_intent"
    AI_INTENT_FIRE_MANUAL = "ai_intent_fire_manual"
    AI_INTENT_TEAM_RECOMMEND = "ai_intent_team_recommend"
    BILI_PUSH = "bili_push"
    BILI_QUERY = "bili_query"
    BLACKLIST = "blacklist"
    FIRE_MANUAL_AD = "fire_manual_ad"
    HELP = "help"
    IMAGE = "image"
    LUCKY_SKIN_WINDOW = "lucky_skin_window"
    MEETING = "meeting"
    PET_CONFIG = "pet_config"
    PLAYER_LINEUP_PRIVATE = "player_lineup_private"
    SEER = "seer"
    SEER_ACTIVITY_PUSH = "seer_activity_push"
    SEER_ACTIVITY_QUERY = "seer_activity_query"
    SEER_AUTOCARD = "seer_autocard"
    SEER_DATA = "seer_data"
    SEER_EQUIPMENT = "seer_equipment"
    SEER_MINTMARK = "seer_mintmark"
    SEER_PEAK = "seer_peak"
    SEER_PET = "seer_pet"
    SEER_PLAYER = "seer_player"
    SEER_RANK = "seer_rank"
    SEER_TEAM = "seer_team"
    SEER_TYPE = "seer_type"
    SEERINFO = "seerinfo"
    SERVER_STATUS_QUERY = "server_status_query"
    TEAM_AUDIT = "team_audit"
    TEAM_RESOURCE_SUBSCRIPTION = "team_resource_subscription"
    TEXT = "text"
    TEXT_PUSH = "text_push"
    WEB_ACTIVITY_LINK = "web_activity_link"
    WEB_ACTIVITY_PUSH = "web_activity_push"


FIRE_MANUAL_AD_FEATURE: Final = Feature.FIRE_MANUAL_AD.value
FIRE_MANUAL_INTENT_FEATURE: Final = Feature.AI_INTENT_FIRE_MANUAL.value
FEATURE_KEYS: Final[frozenset[str]] = frozenset(feature.value for feature in Feature)

SEER_FEATURES: Final[frozenset[str]] = frozenset(
    {
        "seer_player",
        "seer_team",
        "seer_pet",
        "seer_mintmark",
        "seer_equipment",
        "seer_type",
        "seer_peak",
        "seer_autocard",
        "seer_rank",
        "seer_data",
    }
)

FEATURE_BUNDLES: Final[dict[str, frozenset[str]]] = {
    "all": (FEATURE_KEYS - {"admin_notice", "blacklist", "seer"}) | SEER_FEATURES,
    "seer": SEER_FEATURES,
    "query": frozenset(
        {
            "pet_config",
            *SEER_FEATURES,
            "image",
            "bili_query",
            "seer_activity_query",
            "server_status_query",
        }
    ),
    "bili": frozenset({"bili_query", "bili_push"}),
    "seer_activity": frozenset({"seer_activity_query", "seer_activity_push"}),
    "server_status": frozenset({"server_status_query"}),
    "text": frozenset({"text", "web_activity_link", "seerinfo"}),
    "text_push": frozenset({"text_push", "web_activity_push"}),
    "message": frozenset(
        {
            "text",
            "text_push",
            "web_activity_link",
            "web_activity_push",
            "seerinfo",
            "team_audit",
            "team_resource_subscription",
            "ai_intent_team_recommend",
        }
    ),
}

REGISTERED_FEATURE_KEYS: Final[frozenset[str]] = FEATURE_KEYS | frozenset(
    FEATURE_BUNDLES
)


class FeatureBundleConfigError(ValueError):
    @classmethod
    def empty_name(cls) -> FeatureBundleConfigError:
        return cls("features.bundles contains an empty bundle name")

    @classmethod
    def registered_name(cls, names: Iterable[str]) -> FeatureBundleConfigError:
        return cls(
            "features.bundles cannot replace registered feature key(s): "
            + ", ".join(names)
        )

    @classmethod
    def action_bundle_name(
        cls,
        names: Iterable[str],
    ) -> FeatureBundleConfigError:
        return cls(
            "messaging action feature cannot use registered bundle key(s): "
            + ", ".join(names)
        )

    @classmethod
    def cycle(cls, names: Iterable[str]) -> FeatureBundleConfigError:
        return cls("features.bundles contains a cycle: " + " -> ".join(names))

    @classmethod
    def empty_bundle(cls, name: str) -> FeatureBundleConfigError:
        return cls(f"features.bundles.{name} must not be empty")

    @classmethod
    def unknown_item(
        cls,
        name: str,
        index: int,
        item: str,
    ) -> FeatureBundleConfigError:
        return cls(f"features.bundles.{name}[{index}]={item} is not registered")

    @classmethod
    def admin_notice(cls, name: str) -> FeatureBundleConfigError:
        return cls(
            f"features.bundles.{name} must not include admin_notice; "
            "grant it explicitly in a target policy"
        )

    @classmethod
    def all_disallowed_item(
        cls,
        index: int,
        item: str,
    ) -> FeatureBundleConfigError:
        return cls(
            "features.bundles.all must not include protected feature "
            f"at index {index}: {item}"
        )

    @classmethod
    def all_bundle_item(
        cls,
        index: int,
        item: str,
    ) -> FeatureBundleConfigError:
        return cls(
            "features.bundles.all only accepts atomic feature names; "
            f"index {index} references bundle {item}"
        )

    @classmethod
    def all_empty_item(cls, index: int) -> FeatureBundleConfigError:
        return cls(f"features.bundles.all[{index}] must not be empty")


class FeaturePolicyConfigError(ValueError):
    @classmethod
    def empty_target_reference(cls) -> FeaturePolicyConfigError:
        return cls("feature policy contains an empty target reference")


def _coerce_feature_bundles(value: object) -> dict[str, list[str]]:
    parsed = json_object(value, name="feature bundles")
    result: dict[str, list[str]] = {}
    for raw_key, raw_features in parsed.items():
        key = str(raw_key).strip()
        if not key:
            raise FeatureBundleConfigError.empty_name()
        result[key] = _feature_bundle_items(raw_features)
    return result


def _feature_bundle_items(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        raw_items: Iterable[object] = (
            json_array(text, name="feature bundle entries")
            if text.startswith("[")
            else csv_items(text)
        )
        if not raw_items:
            raw_items = ("",)
    elif isinstance(value, Iterable) and not isinstance(value, Mapping):
        raw_items = value
    else:
        raw_items = (value,)
    return unique_items(str(raw_item).strip() for raw_item in raw_items)


class _FeatureBundleResolver:
    def __init__(
        self,
        custom_bundles: Mapping[str, list[str]],
        *,
        feature_keys: frozenset[str],
        built_in_bundles: Mapping[str, frozenset[str]],
    ) -> None:
        self._custom_bundles = custom_bundles
        self._feature_keys = feature_keys
        self._resolved = dict(built_in_bundles)
        self._resolving: list[str] = []

    def resolve_all(self) -> dict[str, frozenset[str]]:
        for bundle_name in self._custom_bundles:
            self._expand(bundle_name)
        return self._resolved

    def _expand(self, name: str) -> frozenset[str]:
        if name in self._resolved:
            return self._resolved[name]
        if name in self._resolving:
            cycle_start = self._resolving.index(name)
            raise FeatureBundleConfigError.cycle([*self._resolving[cycle_start:], name])

        entries = self._custom_bundles[name]
        if not entries:
            raise FeatureBundleConfigError.empty_bundle(name)

        self._resolving.append(name)
        expanded: set[str] = set()
        for index, item in enumerate(entries):
            expanded.update(self._expand_item(name, index, item))
        self._resolving.pop()

        if Feature.ADMIN_NOTICE.value in expanded:
            raise FeatureBundleConfigError.admin_notice(name)
        bundle = frozenset(expanded)
        self._resolved[name] = bundle
        return bundle

    def _expand_item(self, name: str, index: int, item: str) -> frozenset[str]:
        if item in self._custom_bundles or item in self._resolved:
            return self._expand(item)
        if item in self._feature_keys:
            return frozenset((item,))
        raise FeatureBundleConfigError.unknown_item(name, index, item)


def _normalize_feature_keys(features: Iterable[str]) -> frozenset[str]:
    return frozenset(
        feature for raw_feature in features if (feature := str(raw_feature).strip())
    )


def _built_in_bundles_with_message_features(
    *,
    command_features: frozenset[str],
    schedule_features: frozenset[str],
) -> dict[str, frozenset[str]]:
    bundles = dict(FEATURE_BUNDLES)
    safe_commands = command_features - {Feature.ADMIN_NOTICE.value}
    safe_schedules = schedule_features - {Feature.ADMIN_NOTICE.value}
    message_features = safe_commands | safe_schedules
    bundles["all"] = bundles["all"] | message_features
    bundles["text"] = bundles["text"] | safe_commands
    bundles["text_push"] = bundles["text_push"] | safe_schedules
    bundles["message"] = bundles["message"] | message_features
    return bundles


def resolve_feature_bundles(
    custom_bundles: Mapping[str, list[str]],
    *,
    command_features: Iterable[str] = (),
    schedule_features: Iterable[str] = (),
) -> dict[str, frozenset[str]]:
    """Validate and expand configured bundles into atomic feature keys."""

    normalized_commands = _normalize_feature_keys(command_features)
    normalized_schedules = _normalize_feature_keys(schedule_features)
    configured_features = normalized_commands | normalized_schedules
    configured_all = custom_bundles.get("all", [])
    non_all_custom_bundles = {
        name: entries for name, entries in custom_bundles.items() if name != "all"
    }
    custom_all_features = _resolve_custom_all_features(
        configured_all,
        custom_bundle_names=frozenset(non_all_custom_bundles),
    )
    action_bundle_collisions = sorted(
        (configured_features - FEATURE_KEYS) & frozenset(FEATURE_BUNDLES)
    )
    if action_bundle_collisions:
        raise FeatureBundleConfigError.action_bundle_name(action_bundle_collisions)

    feature_keys = FEATURE_KEYS | configured_features | custom_all_features
    built_in_bundles = _built_in_bundles_with_message_features(
        command_features=normalized_commands,
        schedule_features=normalized_schedules,
    )
    built_in_bundles["all"] = built_in_bundles["all"] | custom_all_features
    collisions = sorted(
        set(non_all_custom_bundles) & (feature_keys | frozenset(built_in_bundles))
    )
    if collisions:
        raise FeatureBundleConfigError.registered_name(collisions)
    return _FeatureBundleResolver(
        non_all_custom_bundles,
        feature_keys=feature_keys,
        built_in_bundles=built_in_bundles,
    ).resolve_all()


def _resolve_custom_all_features(
    entries: Iterable[str],
    *,
    custom_bundle_names: frozenset[str],
) -> frozenset[str]:
    declared: set[str] = set()
    for index, raw_entry in enumerate(entries):
        entry = raw_entry.strip()
        if not entry:
            raise FeatureBundleConfigError.all_empty_item(index)
        if entry in {
            Feature.ADMIN_NOTICE.value,
            Feature.BLACKLIST.value,
        }:
            raise FeatureBundleConfigError.all_disallowed_item(index, entry)
        if entry in FEATURE_BUNDLES or entry in custom_bundle_names:
            raise FeatureBundleConfigError.all_bundle_item(index, entry)
        declared.add(entry)
    return frozenset(declared)


POKE_REPLY_REQUIRED_ERROR = (
    "features.help.poke_replies requires non-empty group refs and messages"
)


def _coerce_alias_mapping(
    value: object,
    *,
    location: str,
) -> dict[str, int]:
    parsed = json_object(value, name="feature aliases")
    return normalize_alias_mapping(parsed, location=location)


def _coerce_policy_mapping(value: object) -> dict[str, list[str]]:
    parsed = json_object(value, name="feature policy")
    result: dict[str, list[str]] = {}
    for raw_key, raw_features in parsed.items():
        key = str(raw_key).strip()
        if not key:
            raise FeaturePolicyConfigError.empty_target_reference()
        result[key] = string_list(raw_features)
    return result


class HelpConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ignored_plugins: NormalizedStringList = Field(default_factory=list)
    poke_replies: dict[str, str] = Field(default_factory=dict)
    poke_user_replies: dict[str, str] = Field(default_factory=dict)
    hint_window_seconds: float = Field(default=60.0, gt=0)
    hint_max_per_window: int = Field(default=3, ge=1)
    poke_new_command_initial_weight: float = Field(default=5.0, ge=1.0)
    poke_new_command_half_life_days: float = Field(default=5.0, gt=0.0)

    @field_validator("poke_replies", "poke_user_replies")
    @classmethod
    def normalize_poke_replies(cls, value: dict[str, str]) -> dict[str, str]:
        replies: dict[str, str] = {}
        for raw_group, raw_message in value.items():
            group = raw_group.strip()
            message = raw_message.strip()
            if not group or not message:
                raise ValueError(POKE_REPLY_REQUIRED_ERROR)
            replies[group] = message
        return replies


class FeatureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_aliases: dict[str, int] = Field(default_factory=dict)
    user_aliases: dict[str, int] = Field(default_factory=dict)
    bundles: dict[str, list[str]] = Field(default_factory=dict)
    group_policy: dict[str, list[str]] = Field(default_factory=dict)
    user_policy: dict[str, list[str]] = Field(default_factory=dict)
    superuser_bypass: bool = True
    help: HelpConfig = Field(default_factory=HelpConfig)

    @field_validator("group_aliases", mode="before")
    @classmethod
    def normalize_group_aliases(cls, value: object) -> object:
        return _coerce_alias_mapping(value, location="features.group_aliases")

    @field_validator("user_aliases", mode="before")
    @classmethod
    def normalize_user_aliases(cls, value: object) -> object:
        return _coerce_alias_mapping(value, location="features.user_aliases")

    @field_validator("bundles", mode="before")
    @classmethod
    def normalize_bundles(cls, value: object) -> object:
        return _coerce_feature_bundles(value)

    @field_validator("group_policy", "user_policy", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        return _coerce_policy_mapping(value)


def validate_feature_config(
    config: FeatureConfig,
    *,
    command_features: Iterable[str] = (),
    schedule_features: Iterable[str] = (),
) -> dict[str, frozenset[str]]:
    normalized_commands = _normalize_feature_keys(command_features)
    normalized_schedules = _normalize_feature_keys(schedule_features)
    configured_features = normalized_commands | normalized_schedules
    resolved_bundles = resolve_feature_bundles(
        config.bundles,
        command_features=normalized_commands,
        schedule_features=normalized_schedules,
    )
    registered_policy_keys = (
        FEATURE_KEYS
        | configured_features
        | _resolve_custom_all_features(
            config.bundles.get("all", []),
            custom_bundle_names=frozenset(config.bundles) - {"all"},
        )
        | frozenset(resolved_bundles)
    )
    invalid: list[str] = []
    for policy_name, policy in (
        ("features.group_policy", config.group_policy),
        ("features.user_policy", config.user_policy),
    ):
        for target, features in policy.items():
            for index, raw_feature in enumerate(features):
                feature = raw_feature.strip()
                if not feature or feature in registered_policy_keys:
                    continue
                invalid.append(f"{policy_name}.{target}[{index}]={feature}")

    if invalid:
        raise ValueError("unregistered feature policy key(s): " + ", ".join(invalid))
    return resolved_bundles


@dataclass(frozen=True, slots=True)
class FeatureService:
    config: FeatureConfig
    superuser_ids: frozenset[int]
    command_features: frozenset[str] = frozenset()
    schedule_features: frozenset[str] = frozenset()
    _bundles: Mapping[str, frozenset[str]] = dataclass_field(
        init=False,
        repr=False,
    )
    _references: OneBotReferenceResolver = dataclass_field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        resolved_bundles = validate_feature_config(
            self.config,
            command_features=self.command_features,
            schedule_features=self.schedule_features,
        )
        object.__setattr__(
            self,
            "_bundles",
            resolved_bundles,
        )
        object.__setattr__(
            self,
            "_references",
            OneBotReferenceResolver(
                group_aliases=self.config.group_aliases,
                user_aliases=self.config.user_aliases,
            ),
        )

    def is_superuser(self, user_id: int) -> bool:
        return user_id in self.superuser_ids

    def is_conversation_blocked(
        self,
        user_id: int,
        group_id: int | None = None,
    ) -> bool:
        """Whether an incoming private or group message must be ignored."""

        return self.user_has_feature(user_id, Feature.BLACKLIST.value) or (
            group_id is not None
            and self.group_has_feature(group_id, Feature.BLACKLIST.value)
        )

    def resolve_group_refs(self, refs: Iterable[object]) -> list[int]:
        return self._references.resolve_groups(
            refs,
            location="configured group refs",
        )

    def resolve_user_refs(self, refs: Iterable[object]) -> list[int]:
        return self._references.resolve_users(
            refs,
            location="configured user refs",
        )

    def groups_for_feature(self, feature: str) -> list[int]:
        return self._ids_for_feature(
            self.config.group_policy,
            resolve=self._references.resolve_group,
            feature=feature,
            location="features.group_policy",
        )

    def users_for_feature(self, feature: str) -> list[int]:
        return self._ids_for_feature(
            self.config.user_policy,
            resolve=self._references.resolve_user,
            feature=feature,
            location="features.user_policy",
        )

    def users_with_superusers(self, user_ids: Iterable[int]) -> list[int]:
        return unique_items([*user_ids, *self.superuser_ids])

    def group_has_feature(self, group_id: int, feature: str) -> bool:
        return group_id in self.groups_for_feature(feature)

    def is_group_feature_allowed(
        self,
        user_id: int,
        group_id: int,
        feature: str,
    ) -> bool:
        return self.group_has_feature(group_id, feature) or (
            self.config.superuser_bypass and self.is_superuser(user_id)
        )

    def is_private_feature_allowed(self, user_id: int, feature: str) -> bool:
        return self.user_has_feature(user_id, feature) or (
            self.config.superuser_bypass and self.is_superuser(user_id)
        )

    def user_has_feature(self, user_id: int, feature: str) -> bool:
        return user_id in self.users_for_feature(feature)

    def _ids_for_feature(
        self,
        policy: Mapping[str, list[str]],
        *,
        resolve: Callable[..., int],
        feature: str,
        location: str,
    ) -> list[int]:
        return unique_items(
            resolve(raw_key, location=f"{location}.{raw_key}")
            for raw_key, features in policy.items()
            if self._feature_matches(features, feature)
        )

    def _feature_matches(self, features: Iterable[str], feature: str) -> bool:
        normalized = {item.strip() for item in features if item.strip()}
        return feature in normalized or any(
            feature in self._bundles.get(item, frozenset()) for item in normalized
        )
