# SPDX-License-Identifier: MIT
"""Configured Seer account identities shared by commands and headless services."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ironsbot.core.commands import normalize_command_text
from ironsbot.core.seer_ids import is_valid_player_id

if TYPE_CHECKING:
    from collections.abc import Iterable


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
    query_worker: bool
    password: str | None

    @property
    def display(self) -> str:
        return f"{self.name}（{self.player_id}）"


class PlayerAccountRegistry:
    """Resolve numeric IDs and configured account names to stable player IDs."""

    def __init__(self, accounts: Iterable[PlayerAccount]) -> None:
        by_player_id: dict[int, PlayerAccount] = {}
        by_name: dict[str, PlayerAccount] = {}
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
                if normalized in by_name:
                    raise PlayerAccountReferenceError.duplicate_name(
                        "seer.player_accounts",
                        value,
                    )
                by_name[normalized] = account
        self._by_player_id = by_player_id
        self._by_name = by_name

    @property
    def accounts(self) -> tuple[PlayerAccount, ...]:
        return tuple(self._by_player_id.values())

    @property
    def query_workers(self) -> tuple[PlayerAccount, ...]:
        return tuple(
            account for account in self.accounts if account.query_worker
        )

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
        account = self._by_name.get(normalize_command_text(value))
        if account is None:
            raise PlayerAccountReferenceError.unknown_account(location, value)
        return account

    def resolve_player_id(self, value: object) -> int | None:
        """Resolve a user command target; unknown text remains a normal miss."""

        text = str(value).strip()
        if not text:
            return None
        if text.isdecimal():
            player_id = int(text)
            return player_id if is_valid_player_id(player_id) else None
        account = self._by_name.get(normalize_command_text(text))
        return account.player_id if account is not None else None

    def account_for_player_id(self, player_id: int) -> PlayerAccount | None:
        return self._by_player_id.get(player_id)


def build_player_account_registry(
    entries: Iterable[object],
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
                query_worker=bool(getattr(entry, "query_worker", False)),
                password=_optional_password(getattr(entry, "password", None)),
            )
        )
    return PlayerAccountRegistry(accounts)


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
