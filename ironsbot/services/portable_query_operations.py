# SPDX-License-Identifier: MIT
"""Build portable query operations from typed query specifications."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from ironsbot.core.message_input import MessageInputContext
    from ironsbot.core.outbound import OutboundMessage
    from ironsbot.services.portable_query_sessions import (
        PortableQueryOperation,
        PortableQuerySessions,
        QueryOperationSpec,
    )

_T = TypeVar("_T")


def build_query_operation(
    sessions: PortableQuerySessions,
    spec: QueryOperationSpec[_T],
) -> PortableQueryOperation:
    """Adapt one query service without duplicating its command grammar."""

    async def execute(
        text: str,
        context: MessageInputContext,
    ) -> OutboundMessage | None:
        argument = spec.parser(text)
        if argument is None:
            msg = f"catalog accepted input that its query parser rejected: {text!r}"
            raise ValueError(msg)
        return await sessions.begin(context, argument=argument, spec=spec)

    return execute
