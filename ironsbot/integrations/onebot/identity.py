# SPDX-License-Identifier: MIT
"""OneBot-native identity conversion at the transport boundary."""

from __future__ import annotations

from ironsbot.core.platform import ActorRef, ConversationRef, Platform


def onebot_actor_ref(user_id: int | str) -> ActorRef:
    """Convert one native OneBot user identifier into an opaque actor ref."""

    return ActorRef(Platform.ONEBOT, str(user_id))


def onebot_conversation_ref(
    user_id: int | str,
    *,
    group_id: int | str | None = None,
) -> ConversationRef:
    """Convert one OneBot private or group target into a conversation ref."""

    return ConversationRef(
        Platform.ONEBOT,
        "group" if group_id is not None else "private",
        str(group_id if group_id is not None else user_id),
    )
