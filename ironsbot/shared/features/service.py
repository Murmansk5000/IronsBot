# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.config.models.feature import FeatureConfig, unique_ints
from ironsbot.core.features import FEATURE_BUNDLES

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


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
        return unique_ints([*user_ids, *self.superuser_ids])

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
        return unique_ints(
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
        return unique_ints(
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
