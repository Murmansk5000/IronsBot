# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ironsbot.core.commands import json_object, string_list, unique_items
from ironsbot.core.features import REGISTERED_FEATURE_KEYS

if TYPE_CHECKING:
    from collections.abc import Iterable


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

    @model_validator(mode="after")
    def validate_registered_policy_features(self) -> FeatureConfig:
        invalid: list[str] = []
        for policy_name, policy in (
            ("feature.group_policy", self.group_policy),
            ("feature.user_policy", self.user_policy),
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


def unique_ints(values: Iterable[int]) -> list[int]:
    return unique_items(values)


__all__ = [
    "FeatureConfig",
    "unique_ints",
]
