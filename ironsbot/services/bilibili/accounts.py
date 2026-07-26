from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from ironsbot.core.bilibili import BiliConfig

logger = logging.getLogger(__name__)


def normalize_account_alias(value: object) -> str:
    return str(value).strip().lower()


def account_uid(alias: str, config: BiliConfig) -> int | None:
    account = config.accounts.get(normalize_account_alias(alias))
    return account.uid if account is not None else None


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

    def resolve(self, reference: str, uids: Iterable[int]) -> int | None:
        folded = reference.strip().casefold()
        if not folded:
            return None
        allowed_uids = tuple(dict.fromkeys(int(uid) for uid in uids))
        if folded.isdecimal():
            uid = int(folded)
            return uid if uid in allowed_uids else None
        matches = [
            uid
            for uid in allowed_uids
            if (name := self.name_for_uid(uid)) is not None
            and name.casefold() == folded
        ]
        return matches[0] if len(matches) == 1 else None
