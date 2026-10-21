# SPDX-License-Identifier: MIT
"""Own-account admission and echo protection; message replay belongs to ingress."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import TYPE_CHECKING

from ironsbot.core.outbound import DeliveryFailureKind
from ironsbot.core.own_commands import OwnAccountCommand
from ironsbot.core.platform import Platform
from ironsbot.services.seer.player_query import extract_player_binding_arg

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.transport import SelfCommandsConfig
    from ironsbot.core.outbound import SendResult
    from ironsbot.core.own_commands import OwnAccountInput
    from ironsbot.core.platform import ConversationRef

_RETENTION_SECONDS = 600
_MAX_RECORDS = 4096
_EchoKey = tuple[str, "ConversationRef", str, tuple[str, ...]]


@dataclass(slots=True)
class _EchoState:
    recorded_at: float
    pending: int = 0
    retained_at: float | None = None

    def blocks(self, now: float) -> bool:
        return self.pending > 0 or (
            self.retained_at is not None and self.retained_at > now - _RETENTION_SECONDS
        )


@dataclass(slots=True)
class OwnAccountEcho:
    key: _EchoKey
    state: _EchoState
    recorded_at: float
    settled: bool = False


class OwnAccountCommandPolicy:
    def __init__(
        self, config: SelfCommandsConfig, *, clock: Callable[[], float] = monotonic
    ) -> None:
        self.config = config
        self._clock = clock
        self._echoes: OrderedDict[_EchoKey, _EchoState] = OrderedDict()

    def accept(self, incoming: OwnAccountInput) -> OwnAccountCommand | None:
        command = self._command(incoming)
        if command is None:
            return None
        now = self._clock()
        self._prune(now)
        key = self._key(incoming)
        state = self._echoes.get(key)
        if state is not None:
            if state.blocks(now):
                return None
            del self._echoes[key]
        return command

    def begin_outbound(self, outgoing: OwnAccountInput) -> OwnAccountEcho | None:
        if self._command(outgoing) is None:
            return None
        now = self._clock()
        self._prune(now)
        key = self._key(outgoing)
        state = self._echoes.setdefault(key, _EchoState(now))
        state.recorded_at = now
        state.pending += 1
        self._echoes.move_to_end(key)
        self._prune(now)
        return OwnAccountEcho(key, state, now)

    def finish_outbound(
        self, echo: OwnAccountEcho | None, result: SendResult | None
    ) -> None:
        if echo is None or echo.settled or self._echoes.get(echo.key) is not echo.state:
            return
        echo.settled = True
        state = echo.state
        state.pending -= 1
        retained = (
            result is None
            or result.delivered
            or (
                result.attempted
                and result.failure_kind in {None, DeliveryFailureKind.UNCERTAIN}
            )
        )
        if retained:
            state.retained_at = (
                echo.recorded_at
                if state.retained_at is None
                else max(state.retained_at, echo.recorded_at)
            )
        if not state.blocks(self._clock()):
            del self._echoes[echo.key]

    def _command(self, incoming: OwnAccountInput) -> OwnAccountCommand | None:
        if (
            incoming.conversation.platform is not Platform.ONEBOT
            or incoming.conversation.kind != "group"
            or not incoming.is_own_message
            or incoming.has_other_segments
        ):
            return None
        text = incoming.text
        binding = extract_player_binding_arg(text)
        if (
            binding is not None
            and binding.isdecimal()
            and len(incoming.mentioned_ids) == 1
            and incoming.mentioned_ids[0].isdecimal()
            and incoming.mentioned_ids[0] != incoming.account_id
        ):
            return OwnAccountCommand(text.strip(), admin_binding=True)
        if not self.config.enabled or incoming.mentioned_ids:
            return None
        prefix = next((p for p in self.config.prefixes if text.startswith(p)), None)
        if prefix is None or not (command := text[len(prefix) :].strip()):
            return None
        return OwnAccountCommand(command)

    @staticmethod
    def _key(incoming: OwnAccountInput) -> _EchoKey:
        return (
            incoming.account_id,
            incoming.conversation,
            incoming.text,
            incoming.mentioned_ids,
        )

    def _prune(self, now: float) -> None:
        while self._echoes and (
            next(iter(self._echoes.values())).recorded_at <= now - _RETENTION_SECONDS
            or len(self._echoes) > _MAX_RECORDS
        ):
            self._echoes.popitem(last=False)
