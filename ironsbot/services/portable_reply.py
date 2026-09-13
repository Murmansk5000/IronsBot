# SPDX-License-Identifier: MIT
"""Delivery-aware values shared by portable command runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.services.seer.data_queries import DataQueryImageReply


@dataclass(frozen=True, slots=True)
class PortableReply:
    """One prepared reply with work committed only after transport success."""

    message: OutboundMessage
    on_delivered: Callable[[], None] | None = None

    def delivered(self) -> None:
        if self.on_delivered is not None:
            self.on_delivered()


class PortableOperation(Protocol):
    def __call__(
        self,
        text: str,
        context: MessageInputContext,
    ) -> Awaitable[
        PortableReply | OutboundMessage | str | DataQueryImageReply
    ]: ...
