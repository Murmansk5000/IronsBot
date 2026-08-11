# SPDX-License-Identifier: MIT
"""Configured Seer account identities shared by commands and headless services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.commands import normalize_command_text
from ironsbot.core.seer_ids import is_valid_player_id

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping


class PlayerAccountReferenceError(ValueError):
    """Raised when a configured or user-facing Seer account reference is invalid."""

    @classmethod
    def empty_name(cls, location: str) -> PlayerAccountReferenceError:
        return cls(f"{location} must not be empty")

    @classmethod
    def numeric_name(cls, location: str, value: str) -> PlayerAccountReferenceError:
        return cls(f"{location} must not use a numeric name or alias: {value}")

    @classmethod
    def duplicate_player_id(
        cls,
        location: str,
        player_id: int,
    ) -> PlayerAccountReferenceError:
        return cls(f"{location} repeats player_id {player_id}")

    @classmethod
    def duplicate_name(cls, location: str, value: str) -> PlayerAccountReferenceError:
        return cls(f"{location} repeats player account name or alias: {value}")

    @classmethod
    def unknown_account(
        cls,
        location: str,
        value: object,
    ) -> PlayerAccountReferenceError:
        return cls(f"{location} references unknown player account: {value}")

    @classmethod
    def invalid_player_id(cls, location: str) -> PlayerAccountReferenceError:
        return cls(f"{location} must be a valid Seer player ID or known account name")


@dataclass(frozen=True, slots=True)
class PlayerAccount:
    player_id: int
    name: str
    aliases: tuple[str, ...]
    password: str | None
    public: bool = False

    @property
    def display(self) -> str:
        return f"{self.name}（{self.player_id}）"


class PlayerAccountRegistry:
    """Resolve numeric IDs plus public and group-scoped account aliases."""

    def __init__(
        self,
        accounts: Iterable[PlayerAccount],
        *,
        private_alias_groups: Mapping[int, Iterable[str]] | None = None,
    ) -> None:
        by_player_id: dict[int, PlayerAccount] = {}
        by_reference: dict[str, PlayerAccount] = {}
        public_by_name: dict[str, PlayerAccount] = {}
        for account in accounts:
            if account.player_id in by_player_id:
                raise PlayerAccountReferenceError.duplicate_player_id(
                    "seer.player_accounts",
                    account.player_id,
                )
            by_player_id[account.player_id] = account
            for value in (account.name, *account.aliases):
                normalized = _normalize_name(
                    value,
                    location="seer.player_accounts",
                )
                if normalized in by_reference:
                    raise PlayerAccountReferenceError.duplicate_name(
                        "seer.player_accounts",
                        value,
                    )
                by_reference[normalized] = account
            if account.public:
                for value in (account.name, *account.aliases):
                    public_by_name[_normalize_name(
                        value,
                        location="seer.player_accounts",
                    )] = account
        self._by_player_id = by_player_id
        self._by_reference = by_reference
        self._public_by_name = public_by_name
        self._private_by_group = self._build_private_alias_groups(
            private_alias_groups or {},
        )

    @property
    def accounts(self) -> tuple[PlayerAccount, ...]:
        return tuple(self._by_player_id.values())

    def resolve(self, reference: object, *, location: str) -> PlayerAccount:
        value = str(reference).strip()
        if not value:
            raise PlayerAccountReferenceError.empty_name(location)
        if value.isdecimal():
            player_id = int(value)
            if not is_valid_player_id(player_id):
                raise PlayerAccountReferenceError.invalid_player_id(location)
            account = self._by_player_id.get(player_id)
            if account is None:
                raise PlayerAccountReferenceError.unknown_account(location, value)
            return account
        account = self._by_reference.get(normalize_command_text(value))
        if account is None:
            raise PlayerAccountReferenceError.unknown_account(location, value)
        return account

    def resolve_player_id(
        self,
        value: object,
        *,
        group_id: int | None = None,
        allow_private: bool = False,
    ) -> int | None:
        """Resolve a command target under public, group, or privileged visibility."""

        text = str(value).strip()
        if not text:
            return None
        if text.isdecimal():
            player_id = int(text)
            return player_id if is_valid_player_id(player_id) else None
        normalized = normalize_command_text(text)
        account = (
            self._by_reference.get(normalized)
            if allow_private
            else self._public_by_name.get(normalized)
        )
        if account is None and group_id is not None:
            account = self._private_by_group.get(group_id, {}).get(normalized)
        return account.player_id if account is not None else None

    def account_for_player_id(self, player_id: int) -> PlayerAccount | None:
        return self._by_player_id.get(player_id)

    def _build_private_alias_groups(
        self,
        group_references: Mapping[int, Iterable[str]],
    ) -> dict[int, dict[str, PlayerAccount]]:
        groups: dict[int, dict[str, PlayerAccount]] = {}
        for group_id, references in group_references.items():
            aliases = groups.setdefault(group_id, {})
            for reference in references:
                if reference == "all":
                    accounts = self.accounts
                else:
                    accounts = (self.resolve(
                        reference,
                        location=f"seer.player_account_aliases.{group_id}",
                    ),)
                for account in accounts:
                    for value in (account.name, *account.aliases):
                        aliases[normalize_command_text(value)] = account
        return groups


def build_player_account_registry(
    entries: Iterable[object],
    *,
    private_alias_groups: Mapping[int, Iterable[str]] | None = None,
) -> PlayerAccountRegistry:
    """Build a registry from Pydantic config entries without coupling to models."""

    accounts: list[PlayerAccount] = []
    for index, entry in enumerate(entries):
        location = f"seer.player_accounts[{index}]"
        player_id = getattr(entry, "player_id", None)
        if not isinstance(player_id, int) or not is_valid_player_id(player_id):
            raise PlayerAccountReferenceError.invalid_player_id(
                f"{location}.player_id"
            )
        name = str(getattr(entry, "name", "")).strip()
        _normalize_name(name, location=f"{location}.name")
        aliases = tuple(
            str(value).strip() for value in getattr(entry, "aliases", ())
        )
        for alias_index, alias in enumerate(aliases):
            _normalize_name(
                alias,
                location=f"{location}.aliases[{alias_index}]",
            )
        accounts.append(
            PlayerAccount(
                player_id=player_id,
                name=name,
                aliases=aliases,
                password=_optional_password(getattr(entry, "password", None)),
                public=bool(getattr(entry, "public", False)),
            )
        )
    return PlayerAccountRegistry(
        accounts,
        private_alias_groups=private_alias_groups,
    )


def _normalize_name(value: str, *, location: str) -> str:
    normalized = normalize_command_text(value)
    if not normalized:
        raise PlayerAccountReferenceError.empty_name(location)
    if normalized.isdecimal():
        raise PlayerAccountReferenceError.numeric_name(location, value)
    return normalized


def _optional_password(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
