# SPDX-License-Identifier: MIT
"""Dispatch supported OneBot notices without native models or matchers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import partial
from itertools import groupby
from typing import TYPE_CHECKING, Any

from ironsbot.integrations.onebot.notice_events import (
    decode_notice,
    notice_context,
    notify_onebot_red_packet,
    poke_onebot_member,
    welcome_onebot_member,
)
from ironsbot.integrations.onebot.red_packet import is_red_packet_payload
from ironsbot.services.onebot_admission import OneBotAdmissionInput

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Coroutine

    from ironsbot.config.models.settings import MatcherPriorityConfig
    from ironsbot.core.tasks import TaskSpawner
    from ironsbot.integrations.onebot.connections import OneBotConnection
    from ironsbot.integrations.onebot.notice_events import OneBotNoticeEnvelope
    from ironsbot.integrations.onebot.outbound_messenger import OneBotOutboundMessenger
    from ironsbot.services.messaging.poke_reply import PokeReplyService
    from ironsbot.services.messaging.red_packet import RedPacketNoticeService
    from ironsbot.services.onebot_admission import OneBotAdmissionService
    from ironsbot.services.operations.scheduler import Scheduler
    from ironsbot.services.team.audit import TeamAuditService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _NoticeCall:
    priority: int
    invoke: Callable[[], Awaitable[None]]
    blocks: bool = False


@dataclass(frozen=True, slots=True)
class OneBotNoticeIngress:
    admission: OneBotAdmissionService
    messenger: OneBotOutboundMessenger
    scheduler: Scheduler
    priorities: MatcherPriorityConfig
    spawn: TaskSpawner
    poke: PokeReplyService | None = None
    audit: TeamAuditService | None = None
    red_packets: RedPacketNoticeService | None = None

    async def handle(
        self, connection: OneBotConnection, payload: dict[str, Any]
    ) -> None:
        event = decode_notice(payload)
        if event is None:
            return
        if str(event.self_id) != str(connection.self_id):
            logger.warning("OneBot notice rejected: receiving account mismatch")
            return
        decision = await self.admission.decide(OneBotAdmissionInput())
        if decision.rejection is not None:
            return
        calls = self._calls(connection, event, payload)
        context = notice_context(event.user_id or 0, event.group_id)

        async def run(call: _NoticeCall) -> None:
            try:
                await call.invoke()
            except Exception as error:  # noqa: BLE001 - admin only, never forge a message
                await self.admission.errors.report(context, error, stage="notice")

        for _, grouped in groupby(
            sorted(calls, key=lambda call: call.priority),
            key=lambda call: call.priority,
        ):
            group = tuple(grouped)
            await self._run_group(group, run)
            if any(call.blocks for call in group):
                break

    async def _run_group(
        self,
        calls: tuple[_NoticeCall, ...],
        run: Callable[[_NoticeCall], Coroutine[Any, Any, None]],
    ) -> None:
        tasks: list[asyncio.Task[None]] = []
        try:
            for call in calls:
                coroutine = run(call)
                try:
                    tasks.append(self.spawn(coroutine, name="onebot.notice"))
                except BaseException:
                    coroutine.close()
                    raise
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            # Child cancellation must drain siblings before resources can close.
            drain = asyncio.gather(*tasks, return_exceptions=True)
            while not drain.done():
                try:
                    await asyncio.shield(drain)
                except asyncio.CancelledError:  # noqa: PERF203 - repeated cancellation must still drain
                    continue

    def _calls(
        self,
        connection: OneBotConnection,
        event: OneBotNoticeEnvelope,
        payload: dict[str, Any],
    ) -> list[_NoticeCall]:
        calls: list[_NoticeCall] = []
        if self.poke is not None and event.is_poke_at_bot:
            assert event.user_id is not None
            calls.append(
                _NoticeCall(
                    self.priorities.poke_reply,
                    partial(
                        poke_onebot_member,
                        connection,
                        event.user_id,
                        event.group_id,
                        service=self.poke,
                        messenger=self.messenger,
                    ),
                    blocks=True,
                )
            )
        if self.audit is not None and event.is_group_increase:
            assert event.user_id is not None and event.group_id is not None
            calls.append(
                _NoticeCall(
                    self.priorities.team_audit,
                    partial(
                        welcome_onebot_member,
                        event.self_id,
                        event.user_id,
                        event.group_id,
                        scheduler=self.scheduler,
                        service=self.audit,
                    ),
                )
            )
        if (
            self.red_packets is not None
            and event.group_id is not None
            and is_red_packet_payload(payload)
        ):
            calls.append(
                _NoticeCall(
                    self.priorities.red_packet_notice,
                    partial(
                        notify_onebot_red_packet,
                        connection,
                        event.user_id or 0,
                        event.group_id,
                        service=self.red_packets,
                    ),
                )
            )
        return calls
