from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, Protocol

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ironsbot.core.messaging import MessageTarget


class PendingImageDelivery(NamedTuple):
    dynamic_id: str
    target: MessageTarget
    attempts: int


class BiliImageDeliveryRetryStore(Protocol):
    """Disposable records for image targets whose QQ delivery was ambiguous."""

    def record_failed(
        self,
        dynamic_id: str,
        targets: Iterable[MessageTarget],
    ) -> None: ...

    def list_pending(self, *, limit: int = 100) -> list[PendingImageDelivery]: ...

    def resolve(
        self,
        dynamic_id: str,
        targets: Iterable[MessageTarget],
    ) -> None: ...
