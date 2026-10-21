# SPDX-License-Identifier: MIT
"""Own-account admission and echo protection; message replay belongs to ingress."""

from __future__ import annotations

from collections import OrderedDict
from time import monotonic
from typing import TYPE_CHECKING

from ironsbot.core.own_commands import OwnAccountCommand
from ironsbot.core.platform import Platform
from ironsbot.services.seer.player_query import extract_player_binding_arg

if TYPE_CHECKING:
    from collections.abc import Callable

    from ironsbot.config.models.transport import SelfCommandsConfig
    from ironsbot.core.own_commands import OwnAccountInput

_RETENTION_SECONDS = 600
_MAX_RECORDS = 4096
_EchoKey = tuple[str, str, str, tuple[str, ...]]


class OwnAccountCommandPolicy:
    def __init__(
        self, config: SelfCommandsConfig, *, clock: Callable[[], float] = monotonic
    ) -> None:
        self.config = config
        self._clock = clock
        self._echoes: OrderedDict[_EchoKey, float] = OrderedDict()

    def accept(self, incoming: OwnAccountInput) -> OwnAccountCommand | None:
        command = self._command(incoming)
        if command is None:
            return None
        self._prune(self._clock())
        return None if self._key(incoming) in self._echoes else command

    def record_outbound(self, outgoing: OwnAccountInput) -> None:
        if self._command(outgoing) is None:
            return
        now = self._clock()
        key = self._key(outgoing)
        self._echoes[key] = now
        self._echoes.move_to_end(key)
        self._prune(now)

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
            incoming.conversation.id,
            incoming.text,
            incoming.mentioned_ids,
        )

    def _prune(self, now: float) -> None:
        while self._echoes and (
            next(iter(self._echoes.values())) <= now - _RETENTION_SECONDS
            or len(self._echoes) > _MAX_RECORDS
        ):
            self._echoes.popitem(last=False)
