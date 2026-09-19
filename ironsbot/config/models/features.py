# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.config.models.identities import IdentityConfig
from ironsbot.config.onebot_references import OneBotReferenceResolver
from ironsbot.config.platform_references import (
    PlatformReferenceResolver,
    build_platform_reference_resolver,
)
from ironsbot.core.commands import (
    NormalizedStringList,
    csv_items,
    json_array,
    json_object,
    string_list,
    unique_items,
)
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.features import (
    FEATURE_KEYS,
    SEER_FEATURES,
    Feature,
)
from ironsbot.core.platform import ActorRef, ConversationRef, Platform

if TYPE_CHECKING:
    from ironsbot.config.models.settings import QQOfficialConfig

_PROTECTED_FEATURES: Final[frozenset[str]] = frozenset(
    {
        Feature.ADMIN_NOTICE.value,
        Feature.BLACKLIST.value,
        Feature.QQ_OFFICIAL_IDENTITY_INFO.value,
        Feature.SEER.value,
    }
)

FEATURE_BUNDLES: Final[dict[str, frozenset[str]]] = {
    "all": (FEATURE_KEYS - _PROTECTED_FEATURES) | SEER_FEATURES,
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
        if entry in _PROTECTED_FEATURES:
            raise FeatureBundleConfigError.all_disallowed_item(index, entry)
        if entry in FEATURE_BUNDLES or entry in custom_bundle_names:
            raise FeatureBundleConfigError.all_bundle_item(index, entry)
        declared.add(entry)
    return frozenset(declared)


POKE_REPLY_REQUIRED_ERROR = (
    "features.help.poke_replies requires non-empty group refs and messages"
)


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

    bundles: dict[str, list[str]] = Field(default_factory=dict)
    group_policy: dict[str, list[str]] = Field(default_factory=dict)
    user_policy: dict[str, list[str]] = Field(default_factory=dict)
    superuser_bypass: bool = True
    help: HelpConfig = Field(default_factory=HelpConfig)

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
    qq_official: QQOfficialConfig | None = None,
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
    qq_policies: list[tuple[str, Mapping[str, list[str]]]] = []
    if qq_official is not None:
        for account_name, account in qq_official.enabled_accounts.items():
            qq_policies.extend(
                (
                    (
                        f"bot.qq_official.accounts.{account_name}.features",
                        {"default": account.features},
                    ),
                    (
                        f"bot.qq_official.accounts.{account_name}.group_policy",
                        account.group_policy,
                    ),
                    (
                        f"bot.qq_official.accounts.{account_name}.user_policy",
                        account.user_policy,
                    ),
                )
            )
    for policy_name, policy in (
        ("features.group_policy", config.group_policy),
        ("features.user_policy", config.user_policy),
        *qq_policies,
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


def build_feature_service(  # noqa: PLR0913
    config: FeatureConfig,
    superuser_references: Iterable[object],
    *,
    command_features: Iterable[str] = (),
    schedule_features: Iterable[str] = (),
    qq_official: QQOfficialConfig | None = None,
    references: PlatformReferenceResolver | None = None,
) -> FeatureService:
    """Compile platform configuration into typed policy facts."""

    bundles = validate_feature_config(
        config,
        command_features=command_features,
        schedule_features=schedule_features,
        qq_official=qq_official,
    )
    references = references or build_platform_reference_resolver(
        OneBotReferenceResolver({}, {}),
        IdentityConfig(),
        {},
    )
    group_features: dict[ConversationRef, frozenset[str]] = {}
    for raw_ref, features in config.group_policy.items():
        expanded = _expand_policy_features(features, bundles)
        for conversation in references.group_conversation_refs(
            raw_ref,
            location=f"features.group_policy.{raw_ref}",
        ):
            group_features[conversation] = (
                group_features.get(
                    conversation,
                    frozenset(),
                )
                | expanded
            )

    actor_features: dict[ActorRef, frozenset[str]] = {}
    for raw_ref, features in config.user_policy.items():
        expanded = _expand_policy_features(features, bundles)
        for actor in references.actor_refs(
            raw_ref,
            location=f"features.user_policy.{raw_ref}",
        ):
            actor_features[actor] = actor_features.get(actor, frozenset()) | expanded

    qq_account_defaults: dict[tuple[Platform, str], frozenset[str]] = {}
    if qq_official is not None:
        for account_alias, account in qq_official.enabled_accounts.items():
            account_id = account.app_id
            default_features = _expand_policy_features(account.features, bundles)
            qq_account_defaults[(Platform.QQ_OFFICIAL, account_id)] = default_features
            for reference, features in account.group_policy.items():
                conversation = references.official_group_conversation_ref(
                    reference,
                    account_alias=account_alias,
                    location=(f"bot.qq_official.accounts.{account_alias}.group_policy"),
                )
                group_features[conversation] = group_features.get(
                    conversation,
                    frozenset(),
                ) | _expand_policy_features(features, bundles)
            for reference, features in account.user_policy.items():
                actor = references.official_actor_ref(
                    reference,
                    account_alias=account_alias,
                    location=(f"bot.qq_official.accounts.{account_alias}.user_policy"),
                )
                actor_features[actor] = actor_features.get(
                    actor,
                    frozenset(),
                ) | _expand_policy_features(features, bundles)

    return FeatureService(
        group_features=group_features,
        actor_features=actor_features,
        superusers=frozenset(
            actor
            for reference in superuser_references
            for actor in references.actor_refs(
                reference,
                location="bot.superusers",
            )
        ),
        superuser_bypass=config.superuser_bypass,
        account_default_features=qq_account_defaults,
    )


def _expand_policy_features(
    features: Iterable[str],
    bundles: Mapping[str, frozenset[str]],
) -> frozenset[str]:
    expanded: set[str] = set()
    for raw_feature in features:
        feature = raw_feature.strip()
        if not feature:
            continue
        expanded.update(bundles.get(feature, frozenset((feature,))))
    return frozenset(expanded)
