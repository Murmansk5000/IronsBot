from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ironsbot.core.aliases import AliasIndex

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from ironsbot.core.bilibili import BiliConfig

logger = logging.getLogger(__name__)


def normalize_account_alias(value: object) -> str:
    return str(value).strip().lower()


def configured_account_alias_lookup(
    config: BiliConfig,
    aliases: Iterable[str],
) -> AliasIndex[int]:
    """Build the configured Bilibili alias lookup for one delivery target."""

    return AliasIndex.from_pairs(
        (
            (alias, config.accounts[alias].uid)
            for alias in aliases
            if alias in config.accounts
        ),
        normalizer=normalize_account_alias,
    )


@dataclass(slots=True)
class BiliAccountNames:
    fetch_name: Callable[[int], Awaitable[str | None]] | None = None
    names: dict[int, str] = field(default_factory=dict)
    request_interval_seconds: float = 0.5
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def refresh(self, uids: Iterable[int]) -> bool:
        requested = tuple(dict.fromkeys(int(uid) for uid in uids if int(uid) > 0))
        missing = tuple(uid for uid in requested if not self.name_for_uid(uid))
        if not missing:
            return True
        if self.fetch_name is None:
            return False

        async with self._lock:
            missing = tuple(uid for uid in requested if not self.name_for_uid(uid))
            for index, uid in enumerate(missing):
                try:
                    name = await self.fetch_name(uid)
                except Exception:
                    logger.exception(
                        "failed to fetch Bilibili account name: uid=%s",
                        uid,
                    )
                else:
                    normalized = str(name or "").strip()
                    if normalized:
                        self.names[uid] = normalized
                if (
                    self.request_interval_seconds > 0
                    and index < len(missing) - 1
                ):
                    await asyncio.sleep(self.request_interval_seconds)
        return all(self.name_for_uid(uid) for uid in requested)

    def name_for_uid(self, uid: int) -> str | None:
        name = self.names.get(int(uid), "").strip()
        return name or None

    def public_name_alias_lookup(self, uids: Iterable[int]) -> AliasIndex[int]:
        """Return the public-name/UID aliases that are available to one target."""

        allowed_uids = tuple(dict.fromkeys(int(uid) for uid in uids if int(uid) > 0))
        pairs: list[tuple[str, int]] = [(str(uid), uid) for uid in allowed_uids]
        pairs.extend(
            (name, uid)
            for uid in allowed_uids
            if (name := self.name_for_uid(uid)) is not None
        )
        return AliasIndex.from_pairs(pairs, normalizer=normalize_account_alias)
