# SPDX-License-Identifier: MIT
"""Canonical logical identities shared by every QQ transport."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IdentityTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    qq: int | None = Field(default=None, gt=0)
    official: dict[str, str] = Field(default_factory=dict)

    @field_validator("official", mode="before")
    @classmethod
    def normalize_official(cls, value: object) -> dict[str, str]:
        if not isinstance(value, Mapping):
            msg = "identity official endpoints must be a table"
            raise TypeError(msg)
        endpoints: dict[str, str] = {}
        for raw_account, raw_openid in value.items():
            account = str(raw_account).strip()
            openid = str(raw_openid).strip()
            if not account or not openid:
                msg = "identity official account aliases and OpenIDs must not be empty"
                raise ValueError(msg)
            endpoints[account] = openid
        return endpoints

    @model_validator(mode="after")
    def require_endpoint(self) -> IdentityTarget:
        if self.qq is None and not self.official:
            msg = "identity target must define qq or at least one official endpoint"
            raise ValueError(msg)
        return self


class IdentityConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    groups: dict[str, IdentityTarget] = Field(default_factory=dict)
    users: dict[str, IdentityTarget] = Field(default_factory=dict)

    @field_validator("groups", "users", mode="before")
    @classmethod
    def normalize_aliases(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            msg = "identities groups and users must be tables"
            raise TypeError(msg)
        normalized: dict[str, object] = {}
        for raw_alias, raw_target in value.items():
            alias = str(raw_alias).strip()
            if not alias or alias.isdecimal():
                msg = "identity aliases must be nonempty and nonnumeric"
                raise ValueError(msg)
            normalized[alias] = (
                {"qq": raw_target}
                if isinstance(raw_target, int) and not isinstance(raw_target, bool)
                else raw_target
            )
        return normalized

    @model_validator(mode="after")
    def validate_unique_endpoints(self) -> IdentityConfig:
        _validate_unique_targets(self.groups, kind="group")
        _validate_unique_targets(self.users, kind="user")
        return self


def _validate_unique_targets(
    targets: Mapping[str, IdentityTarget],
    *,
    kind: str,
) -> None:
    qq_aliases: dict[int, str] = {}
    official_aliases: dict[tuple[str, str], str] = {}
    for alias, target in targets.items():
        if target.qq is not None:
            existing = qq_aliases.get(target.qq)
            if existing is not None:
                msg = f"{kind} identities {existing} and {alias} share QQ ID"
                raise ValueError(msg)
            qq_aliases[target.qq] = alias
        for account, openid in target.official.items():
            key = (account, openid)
            existing = official_aliases.get(key)
            if existing is not None:
                msg = (
                    f"{kind} identities {existing} and {alias} share an official "
                    "endpoint"
                )
                raise ValueError(msg)
            official_aliases[key] = alias
