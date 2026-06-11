# SPDX-License-Identifier: MIT
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from nonebot import get_driver
from nonebot.adapters.onebot.v11 import GroupMessageEvent, PrivateMessageEvent

from ironsbot.shared.config.config import (
    FEATURE_ALIASES,
    KNOWN_FEATURES,
    FeaturePolicyConfig,
    get_shared_config,
    unique_ints,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from nonebot.adapters import Event

FeatureContext = object


def _coerce_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class FeatureService:
    """Central access point for feature policy decisions."""

    @property
    def config(self) -> FeaturePolicyConfig:
        return get_shared_config().feature_policy

    def get_superuser_ids(self) -> set[int]:
        superusers = getattr(get_driver().config, "superusers", set())
        user_ids: set[int] = set()
        for user_id in superusers:
            if (int_user_id := _coerce_int(user_id)) is not None:
                user_ids.add(int_user_id)
        return user_ids

    def is_superuser(self, user_id: int) -> bool:
        return user_id in self.get_superuser_ids()

    def is_enabled(  # noqa: C901, PLR0911
        self,
        feature: str,
        context: FeatureContext,
    ) -> bool:
        if isinstance(context, GroupMessageEvent):
            group_id = _coerce_int(context.group_id)
            if group_id is None:
                return False
            return self.is_group_feature_allowed(
                _coerce_int(context.user_id) or 0,
                group_id,
                feature,
            )
        if isinstance(context, PrivateMessageEvent):
            user_id = _coerce_int(context.user_id) or 0
            return self.is_private_feature_allowed(user_id, feature)

        if isinstance(context, int):
            return self.is_private_feature_allowed(context, feature)

        if isinstance(context, Mapping):
            if "group_id" in context or "user_id" in context:
                user_id = _coerce_int(context.get("user_id"))
                group_id = _coerce_int(context.get("group_id"))
                if group_id is not None:
                    return self.is_group_feature_allowed(
                        user_id or 0,
                        group_id,
                        feature,
                    )
                if user_id is not None:
                    return self.is_private_feature_allowed(user_id, feature)
            return False

        user_id = _coerce_int(getattr(context, "user_id", None))
        group_id = _coerce_int(getattr(context, "group_id", None))
        if group_id is not None:
            return self.is_group_feature_allowed(user_id or 0, group_id, feature)
        if user_id is not None:
            return self.is_private_feature_allowed(user_id, feature)
        return False

    def resolve_group_refs(self, refs: Iterable[object]) -> list[int]:
        return self._resolve_policy_refs(refs, self.config.group_aliases)

    def resolve_user_refs(self, refs: Iterable[object]) -> list[int]:
        return self._resolve_policy_refs(refs, self.config.user_aliases)

    def groups_for_feature(self, feature: str) -> list[int]:
        config = self.config
        return self._ids_for_feature(
            config.feature_group_policy,
            config.group_aliases,
            feature,
        )

    def users_for_feature(self, feature: str) -> list[int]:
        config = self.config
        return self._ids_for_feature(
            config.feature_user_policy,
            config.user_aliases,
            feature,
        )

    def resolve_group_policy(self, group_id: int) -> list[str]:
        resolved = _coerce_int(group_id)
        if resolved is None or resolved <= 0:
            return []
        features: list[str] = []
        for raw_key, feature_list in self.config.feature_group_policy.items():
            if self._resolve_policy_id(raw_key, self.config.group_aliases) != resolved:
                continue
            features.extend(self._expand_features(feature_list))
        return self._dedupe_features(features)

    def resolve_user_policy(self, user_id: int) -> list[str]:
        resolved = _coerce_int(user_id)
        if resolved is None or resolved <= 0:
            return []
        features: list[str] = []
        for raw_key, feature_list in self.config.feature_user_policy.items():
            if self._resolve_policy_id(raw_key, self.config.user_aliases) != resolved:
                continue
            features.extend(self._expand_features(feature_list))
        return self._dedupe_features(features)

    def users_with_superusers(self, user_ids: Iterable[int]) -> list[int]:
        return unique_ints([*user_ids, *self.get_superuser_ids()])

    def group_has_feature(self, group_id: int, feature: str) -> bool:
        return group_id in self.groups_for_feature(feature)

    def is_group_feature_allowed(
        self,
        user_id: int,
        group_id: int,
        feature: str,
    ) -> bool:
        if self.group_has_feature(group_id, feature):
            return True
        return self.config.feature_superuser_bypass and self.is_superuser(user_id)

    def is_private_feature_allowed(self, user_id: int, feature: str) -> bool:
        return user_id in self.users_for_feature(feature) or (
            self.config.feature_superuser_bypass and self.is_superuser(user_id)
        )

    def is_event_feature_allowed(self, event: Event, feature: str) -> bool:
        if isinstance(event, GroupMessageEvent):
            group_id = _coerce_int(event.group_id)
            if group_id is None:
                return False
            return self.is_group_feature_allowed(
                _coerce_int(event.user_id) or 0,
                group_id,
                feature,
            )

        if isinstance(event, PrivateMessageEvent):
            user_id = _coerce_int(event.user_id)
            if user_id is None:
                return False
            return self.is_private_feature_allowed(user_id, feature)

        return False

    def _feature_matches(self, features: Iterable[str], feature: str) -> bool:
        normalized = {item.strip() for item in features if item.strip()}
        if "all" in normalized or feature in normalized:
            return True

        return any(
            feature in FEATURE_ALIASES.get(item, frozenset())
            for item in normalized
        )

    def _resolve_policy_id(
        self,
        raw_key: str,
        aliases: Mapping[str, int],
    ) -> int | None:
        key = raw_key.strip()
        if not key:
            return None
        if key in aliases:
            return aliases[key]
        return _coerce_int(key)

    def _ids_for_feature(
        self,
        policy: Mapping[str, list[str]],
        aliases: Mapping[str, int],
        feature: str,
    ) -> list[int]:
        ids: list[int] = []
        for raw_key, features in policy.items():
            if not self._feature_matches(features, feature):
                continue
            resolved_id = self._resolve_policy_id(raw_key, aliases)
            if resolved_id is not None and resolved_id > 0:
                ids.append(resolved_id)
        return unique_ints(ids)

    def _expand_features(self, features: Iterable[str]) -> list[str]:
        return self._normalize_feature_set(self._dedupe_features(features))

    def _resolve_policy_refs(
        self,
        refs: Iterable[object],
        aliases: Mapping[str, int],
    ) -> list[int]:
        ids: list[int] = []
        for raw_ref in refs:
            resolved_id = self._resolve_policy_id(str(raw_ref), aliases)
            if resolved_id is not None and resolved_id > 0:
                ids.append(resolved_id)
        return unique_ints(ids)

    def _normalize_feature_set(self, features: Iterable[str]) -> list[str]:
        normalized: list[str] = []
        for raw_feature in features:
            feature = raw_feature.strip()
            if not feature:
                continue
            if feature in FEATURE_ALIASES:
                normalized.extend(FEATURE_ALIASES[feature])
                continue
            normalized.append(feature)
        return list(dict.fromkeys(normalized))

    def _dedupe_features(self, features: Iterable[str]) -> list[str]:
        return list(
            dict.fromkeys(
                f for f in (str(feature).strip() for feature in features) if f
            )
        )


feature_service = FeatureService()


def get_superuser_ids() -> set[int]:
    return feature_service.get_superuser_ids()


def is_superuser(user_id: int) -> bool:
    return feature_service.is_superuser(user_id)


def resolve_group_refs(refs: Iterable[object]) -> list[int]:
    return feature_service.resolve_group_refs(refs)


def resolve_user_refs(refs: Iterable[object]) -> list[int]:
    return feature_service.resolve_user_refs(refs)


def groups_for_feature(feature: str) -> list[int]:
    return feature_service.groups_for_feature(feature)


def users_for_feature(feature: str) -> list[int]:
    return feature_service.users_for_feature(feature)


def users_with_superusers(user_ids: Iterable[int]) -> list[int]:
    return feature_service.users_with_superusers(user_ids)


def group_has_feature(group_id: int, feature: str) -> bool:
    return feature_service.group_has_feature(group_id, feature)


def is_group_feature_allowed(user_id: int, group_id: int, feature: str) -> bool:
    return feature_service.is_group_feature_allowed(
        user_id=_coerce_int(user_id) or 0,
        group_id=_coerce_int(group_id) or 0,
        feature=feature,
    )


def is_private_feature_allowed(user_id: int, feature: str) -> bool:
    return feature_service.is_private_feature_allowed(
        user_id=_coerce_int(user_id) or 0,
        feature=feature,
    )


def is_enabled(feature: str, context: FeatureContext) -> bool:
    return feature_service.is_enabled(feature, context)


def resolve_group_policy(group_id: int) -> list[str]:
    return feature_service.resolve_group_policy(group_id)


def resolve_user_policy(user_id: int) -> list[str]:
    return feature_service.resolve_user_policy(user_id)


def is_event_feature_allowed(event: Event, feature: str) -> bool:
    return feature_service.is_event_feature_allowed(event, feature)


__all__ = [
    "FEATURE_ALIASES",
    "KNOWN_FEATURES",
    "FeaturePolicyConfig",
    "FeatureService",
    "feature_service",
    "get_superuser_ids",
    "group_has_feature",
    "groups_for_feature",
    "is_enabled",
    "is_event_feature_allowed",
    "is_group_feature_allowed",
    "is_private_feature_allowed",
    "is_superuser",
    "resolve_group_policy",
    "resolve_group_refs",
    "resolve_user_policy",
    "resolve_user_refs",
    "users_for_feature",
    "users_with_superusers",
]
