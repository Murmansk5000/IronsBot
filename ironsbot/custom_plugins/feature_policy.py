# SPDX-License-Identifier: MIT
import json
from collections.abc import Iterable, Mapping
from typing import Any

from nonebot import get_driver, get_plugin_config
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent
from pydantic import BaseModel, Field, field_validator

KNOWN_FEATURES = frozenset(
    {
        "seer",
        "image",
        "rank",
        "meeting",
        "text",
        "text_push",
        "bili_query",
        "bili_push",
        "activity_query",
        "activity_push",
        "server_status_query",
        "server_status_push",
        "team",
        "ai",
        "ai_intent",
        "admin_notice",
    }
)

FEATURE_ALIASES: dict[str, frozenset[str]] = {
    "all": KNOWN_FEATURES - {"admin_notice"},
    "custom": frozenset(
        {
            "seer",
            "image",
            "rank",
            "bili_query",
            "activity_query",
            "server_status_query",
        }
    ),
    "bili": frozenset({"bili_query", "bili_push"}),
    "activity": frozenset({"activity_query", "activity_push"}),
    "server_status": frozenset({"server_status_query", "server_status_push"}),
    "message": frozenset({"text", "text_push"}),
}


def _coerce_mapping(value: object) -> dict[str, Any]:
    if value is None or value == "":
        return {}

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if not isinstance(parsed, Mapping):
            msg = "feature policy values must be JSON objects"
            raise TypeError(msg)
        return dict(parsed)

    if isinstance(value, Mapping):
        return dict(value)

    msg = "feature policy values must be mappings"
    raise TypeError(msg)


def _coerce_int_mapping(value: object) -> dict[str, int]:
    parsed = _coerce_mapping(value)
    result: dict[str, int] = {}
    for raw_key, raw_value in parsed.items():
        key = str(raw_key).strip()
        if not key:
            continue
        result[key] = int(raw_value)
    return result


def _coerce_policy_mapping(value: object) -> dict[str, list[str]]:
    parsed = _coerce_mapping(value)
    result: dict[str, list[str]] = {}
    for raw_key, raw_features in parsed.items():
        key = str(raw_key).strip()
        if not key:
            continue
        if isinstance(raw_features, str):
            features = [
                item.strip()
                for item in raw_features.split(",")
                if item.strip()
            ]
        elif isinstance(raw_features, Iterable):
            features = [
                str(item).strip()
                for item in raw_features
                if str(item).strip()
            ]
        else:
            features = []
        result[key] = list(dict.fromkeys(features))
    return result


class FeaturePolicyConfig(BaseModel):
    group_aliases: dict[str, int] = Field(default_factory=dict)
    user_aliases: dict[str, int] = Field(default_factory=dict)
    feature_group_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_user_policy: dict[str, list[str]] = Field(default_factory=dict)
    feature_superuser_bypass: bool = False

    @field_validator("group_aliases", "user_aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return _coerce_int_mapping(value)

    @field_validator("feature_group_policy", "feature_user_policy", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        return _coerce_policy_mapping(value)


policy_config = get_plugin_config(FeaturePolicyConfig)


def _unique_ints(values: Iterable[int]) -> list[int]:
    return list(dict.fromkeys(values))


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_superuser_ids() -> set[int]:
    superusers = getattr(get_driver().config, "superusers", set())
    user_ids: set[int] = set()
    for user_id in superusers:
        if (int_user_id := _coerce_int(user_id)) is not None:
            user_ids.add(int_user_id)
    return user_ids


def is_superuser(user_id: int) -> bool:
    return user_id in get_superuser_ids()


def _feature_matches(features: Iterable[str], feature: str) -> bool:
    normalized = {item.strip() for item in features if item.strip()}
    if "all" in normalized or feature in normalized:
        return True

    return any(
        feature in FEATURE_ALIASES.get(item, frozenset())
        for item in normalized
    )


def _resolve_policy_id(raw_key: str, aliases: Mapping[str, int]) -> int | None:
    key = raw_key.strip()
    if not key:
        return None
    if key in aliases:
        return aliases[key]
    return _coerce_int(key)


def _ids_for_feature(
    policy: Mapping[str, list[str]],
    aliases: Mapping[str, int],
    feature: str,
) -> list[int]:
    ids: list[int] = []
    for raw_key, features in policy.items():
        if not _feature_matches(features, feature):
            continue
        resolved_id = _resolve_policy_id(raw_key, aliases)
        if resolved_id is not None and resolved_id > 0:
            ids.append(resolved_id)
    return _unique_ints(ids)


def groups_for_feature(feature: str) -> list[int]:
    return _ids_for_feature(
        policy_config.feature_group_policy,
        policy_config.group_aliases,
        feature,
    )


def users_for_feature(feature: str) -> list[int]:
    return _ids_for_feature(
        policy_config.feature_user_policy,
        policy_config.user_aliases,
        feature,
    )


def users_with_superusers(user_ids: Iterable[int]) -> list[int]:
    return _unique_ints([*user_ids, *get_superuser_ids()])


def group_has_feature(group_id: int, feature: str) -> bool:
    return group_id in groups_for_feature(feature)


def is_group_feature_allowed(user_id: int, group_id: int, feature: str) -> bool:
    if group_has_feature(group_id, feature):
        return True
    return policy_config.feature_superuser_bypass and is_superuser(user_id)


def is_private_feature_allowed(user_id: int, feature: str) -> bool:
    return user_id in users_for_feature(feature) or is_superuser(user_id)


def is_event_feature_allowed(event: Event, feature: str) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_feature_allowed(event.user_id, event.group_id, feature)

    if isinstance(event, PrivateMessageEvent):
        return is_private_feature_allowed(event.user_id, feature)

    return False
