from typing import NamedTuple, Protocol

from ironsbot.services.ai.history import HistoryMessage


class AiMemoryTurn(NamedTuple):
    user_id: int
    session_key: str
    chat_scope: str
    chat_id: int
    prompt: str
    reply: str


class AiMemoryStore(Protocol):
    def append(self, turn: AiMemoryTurn) -> None: ...

    def load(
        self,
        *,
        user_id: int,
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
