from typing import NamedTuple, Protocol

from ironsbot.core.platform import ActorRef, ConversationRef
from ironsbot.services.ai.history import HistoryMessage


class AiMemoryTurn(NamedTuple):
    actor: ActorRef
    session_key: str
    conversation: ConversationRef
    prompt: str
    reply: str


class AiMemoryStore(Protocol):
    async def append(self, turn: AiMemoryTurn) -> None: ...

    async def load(
        self,
        *,
        actor: ActorRef,
        current_session_key: str,
        exclude_current_session: bool,
        limit: int,
    ) -> list[HistoryMessage]: ...


def trim_memory_chars(
    messages: list[HistoryMessage],
    max_chars: int,
) -> list[HistoryMessage]:
    used = 0
    selected: list[HistoryMessage] = []
    for message in reversed(messages):
        next_used = used + len(message.get("content", ""))
        if selected and next_used > max_chars:
            break
        used = next_used
        selected.append(message)
    return list(reversed(selected))
