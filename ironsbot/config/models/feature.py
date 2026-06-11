# SPDX-License-Identifier: MIT
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ironsbot.shared.config.config import FEATURE_ALIASES, KNOWN_FEATURES
from ironsbot.shared.config.parsing import json_object, string_list


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


__all__ = [
    "FEATURE_ALIASES",
    "KNOWN_FEATURES",
    "FeatureConfig",
]
