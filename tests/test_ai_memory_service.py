from pathlib import Path

from ironsbot.integrations.storage.ai_memory import SqliteAiMemoryStore
from ironsbot.services.ai.memory import AiMemoryTurn

GROUP_ID = 456
USER_ID = 123


def _append(
    store: SqliteAiMemoryStore,
    session_key: str,
    prompt: str,
    reply: str,
) -> None:
    store.append(
        AiMemoryTurn(
            USER_ID,
            session_key,
            "group",
            GROUP_ID,
            prompt,
            reply,
        )
    )


def test_ai_memory_appends_and_reads_recent_turn(tmp_path: Path) -> None:
    store = SqliteAiMemoryStore(tmp_path / "memory.sqlite")
    _append(store, "session-a", "first prompt", "first reply")
    _append(store, "session-b", "second prompt", "second reply")

    assert store.load(
        user_id=USER_ID,
        current_session_key="current",
        exclude_current_session=False,
        limit=2,
    ) == [
        {"role": "user", "content": "second prompt"},
        {"role": "assistant", "content": "second reply"},
    ]


def test_ai_memory_excludes_current_short_history_session(tmp_path: Path) -> None:
    store = SqliteAiMemoryStore(tmp_path / "memory.sqlite")
    _append(store, "current", "current prompt", "current reply")
    _append(store, "older", "older prompt", "older reply")

    assert store.load(
        user_id=USER_ID,
        current_session_key="current",
        exclude_current_session=True,
        limit=2,
    ) == [
        {"role": "user", "content": "older prompt"},
        {"role": "assistant", "content": "older reply"},
    ]
