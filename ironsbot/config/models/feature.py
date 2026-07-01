# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.shared.config.parsing import json_object, string_list, unique_items

if TYPE_CHECKING:
    from collections.abc import Iterable

KNOWN_FEATURES = frozenset(
    {
        "seer",
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
        "image",
        "rank",
        "meeting",
        "text",
        "text_push",
        "web_activity_link",
        "web_activity_push",
        "seerinfo",
        "bili_query",
        "bili_push",
        "seer_activity_query",
        "seer_activity_push",
        "server_status_query",
        "server_status_push",
        "team_resource_subscription",
        "ai_chat",
        "ai_intent",
        "fire_manual",
        "team_audit",
        "admin_notice",
    }
)
SEER_FEATURES = frozenset(
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
FEATURE_ALIASES: dict[str, frozenset[str]] = {
    "all": (KNOWN_FEATURES - {"admin_notice", "seer"}) | SEER_FEATURES,
    "seer": SEER_FEATURES,
    "query": frozenset(
        {
            *SEER_FEATURES,
            "image",
            "rank",
            "bili_query",
            "seer_activity_query",
            "server_status_query",
        }
    ),
    "rank": frozenset({"rank", "seer_rank"}),
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
        }
    ),
}


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


class FeatureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_aliases: dict[str, int] = Field(default_factory=dict)
    user_aliases: dict[str, int] = Field(default_factory=dict)
    group_policy: dict[str, list[str]] = Field(default_factory=dict)
    user_policy: dict[str, list[str]] = Field(default_factory=dict)
    superuser_bypass: bool = True

    @field_validator("group_aliases", "user_aliases", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        return _coerce_int_mapping(value)

    @field_validator("group_policy", "user_policy", mode="before")
    @classmethod
    def normalize_policy(cls, value: object) -> object:
        return _coerce_policy_mapping(value)


def unique_ints(values: Iterable[int]) -> list[int]:
    return unique_items(values)


__all__ = [
    "FEATURE_ALIASES",
    "KNOWN_FEATURES",
    "SEER_FEATURES",
    "FeatureConfig",
    "unique_ints",
]
