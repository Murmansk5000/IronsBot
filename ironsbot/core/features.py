# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ironsbot.core.commands import (
    NormalizedStringList,
    json_object,
    string_list,
    unique_items,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


class Feature(str, Enum):
    ABOUT = "about"
    ADMIN_NOTICE = "admin_notice"
    AI_CHAT = "ai_chat"
    AI_INTENT = "ai_intent"
    AI_INTENT_FIRE_MANUAL = "ai_intent_fire_manual"
    AI_INTENT_TEAM_RECOMMEND = "ai_intent_team_recommend"
    BILI_PUSH = "bili_push"
    BILI_QUERY = "bili_query"
    FIRE_MANUAL_AD = "fire_manual_ad"
    HELP = "help"
    IMAGE = "image"
    MEETING = "meeting"
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
    SERVER_STATUS_PUSH = "server_status_push"
    SERVER_STATUS_QUERY = "server_status_query"
    TEAM_AUDIT = "team_audit"
    TEAM_RESOURCE_SUBSCRIPTION = "team_resource_subscription"
    TEXT = "text"
    TEXT_PUSH = "text_push"
    WEB_ACTIVITY_LINK = "web_activity_link"
    WEB_ACTIVITY_PUSH = "web_activity_push"


FIRE_MANUAL_AD_FEATURE: Final = Feature.FIRE_MANUAL_AD.value
FIRE_MANUAL_INTENT_FEATURE: Final = Feature.AI_INTENT_FIRE_MANUAL.value
FEATURE_KEYS: Final[frozenset[str]] = frozenset(
    feature.value for feature in Feature
)

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
    "all": (FEATURE_KEYS - {"admin_notice", "seer"}) | SEER_FEATURES,
    "seer": SEER_FEATURES,
    "query": frozenset(
        {
            *SEER_FEATURES,
            "image",
            "bili_query",
            "seer_activity_query",
            "server_status_query",
        }
    ),
    "bili": frozenset({"bili_query", "bili_push"}),
    "activity": frozenset({"seer_activity_query", "seer_activity_push"}),
    "seer_activity": frozenset({"seer_activity_query", "seer_activity_push"}),
    "server_status": frozenset({"server_status_query", "server_status_push"}),
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

REGISTERED_FEATURE_KEYS: Final[frozenset[str]] = (
    FEATURE_KEYS | frozenset(FEATURE_BUNDLES)
)

POKE_REPLY_REQUIRED_ERROR = (
    "features.help.poke_replies requires non-empty group refs and messages"
)


def _coerce_int_mapping(value: object) -> dict[str, int]:
    parsed = json_object(value, name="feature aliases")
    result: dict[str, int] = {}
    for raw_key, raw_value in parsed.items():
        key = str(raw_key).strip()
        if key:
            result[key] = int(raw_value)
    return result


def _coerce_policy_mapping(value: object) -> dict[str, list[str]]:
    parsed = json_object(value, name="feature policy")
    result: dict[str, list[str]] = {}
    for raw_key, raw_features in parsed.items():
        key = str(raw_key).strip()
        if key:
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


class SuperuserPriorityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    wait_timeout_seconds: float = Field(default=300.0, ge=0)


class FeatureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_aliases: dict[str, int] = Field(default_factory=dict)
    user_aliases: dict[str, int] = Field(default_factory=dict)
    group_policy: dict[str, list[str]] = Field(default_factory=dict)
    user_policy: dict[str, list[str]] = Field(default_factory=dict)
    superuser_bypass: bool = True
    help: HelpConfig = Field(default_factory=HelpConfig)
    priority: SuperuserPriorityConfig = Field(
        default_factory=SuperuserPriorityConfig
    )

    @field_validator("group_aliases", "user_aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return _coerce_int_mapping(value)

    @field_validator("group_policy", "user_policy", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        return _coerce_policy_mapping(value)

    @model_validator(mode="after")
    def validate_registered_policy_features(self) -> FeatureConfig:
        invalid: list[str] = []
        for policy_name, policy in (
            ("features.group_policy", self.group_policy),
            ("features.user_policy", self.user_policy),
        ):
            for target, features in policy.items():
                for index, raw_feature in enumerate(features):
                    feature = raw_feature.strip()
                    if not feature or feature in REGISTERED_FEATURE_KEYS:
                        continue
                    invalid.append(f"{policy_name}.{target}[{index}]={feature}")

        if invalid:
            raise ValueError(
                "unregistered feature policy key(s): " + ", ".join(invalid)
            )
        return self


@dataclass(frozen=True, slots=True)
class FeatureService:
    config: FeatureConfig
    superuser_ids: frozenset[int]

    def is_superuser(self, user_id: int) -> bool:
        return user_id in self.superuser_ids

    def resolve_group_refs(self, refs: Iterable[object]) -> list[int]:
        return self._resolve_policy_refs(refs, self.config.group_aliases)

    def resolve_user_refs(self, refs: Iterable[object]) -> list[int]:
        return self._resolve_policy_refs(refs, self.config.user_aliases)

    def groups_for_feature(self, feature: str) -> list[int]:
        return self._ids_for_feature(
            self.config.group_policy,
            self.config.group_aliases,
            feature,
        )

    def users_for_feature(self, feature: str) -> list[int]:
        return self._ids_for_feature(
            self.config.user_policy,
            self.config.user_aliases,
            feature,
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
        return user_id in self.users_for_feature(feature) or (
            self.config.superuser_bypass and self.is_superuser(user_id)
        )

    def _resolve_policy_refs(
        self,
        refs: Iterable[object],
        aliases: Mapping[str, int],
    ) -> list[int]:
        return unique_items(
            resolved
            for raw_ref in refs
            if (resolved := self._resolve_policy_id(str(raw_ref), aliases))
            is not None
            and resolved > 0
        )

    def _ids_for_feature(
        self,
        policy: Mapping[str, list[str]],
        aliases: Mapping[str, int],
        feature: str,
    ) -> list[int]:
        return unique_items(
            resolved_id
            for raw_key, features in policy.items()
            if self._feature_matches(features, feature)
            if (resolved_id := self._resolve_policy_id(raw_key, aliases)) is not None
            and resolved_id > 0
        )

    @staticmethod
    def _feature_matches(features: Iterable[str], feature: str) -> bool:
        normalized = {item.strip() for item in features if item.strip()}
        return feature in normalized or any(
            feature in FEATURE_BUNDLES.get(item, frozenset()) for item in normalized
        )

    @staticmethod
    def _resolve_policy_id(
        raw_key: str,
        aliases: Mapping[str, int],
    ) -> int | None:
        key = raw_key.strip()
        if not key:
            return None
        if key in aliases:
            return aliases[key]
        try:
            return int(key)
        except ValueError:
            return None
