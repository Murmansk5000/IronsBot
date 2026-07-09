from pathlib import Path

from pytest import MonkeyPatch

from ironsbot.services.ai import memory
from tests.helpers.config import stub_ai_memory_config
from tests.helpers.onebot_events import group_message_event

GROUP_ID = 456
USER_ID = 123


def _enable_memory(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        memory,
        "_get_ai_config",
        lambda: stub_ai_memory_config(memory_path=tmp_path / "memory.sqlite"),
    )


def test_ai_memory_appends_and_reads_recent_turn(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_memory(monkeypatch, tmp_path)
    event = group_message_event(user_id=USER_ID, group_id=GROUP_ID)

    memory.append_user_memory(
        event,
        session_key="session-a",
        prompt="first prompt",
        reply="first reply",
    )
    memory.append_user_memory(
        event,
        session_key="session-b",
        prompt="second prompt",
        reply="second reply",
    )

    assert memory.get_user_memory(
        event,
        current_session_key="current",
        has_short_history=False,
    ) == [
        {"role": "user", "content": "second prompt"},
        {"role": "assistant", "content": "second reply"},
    ]


def test_ai_memory_excludes_current_short_history_session(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_memory(monkeypatch, tmp_path)
    event = group_message_event(user_id=USER_ID, group_id=GROUP_ID)

    memory.append_user_memory(
        event,
        session_key="current",
        prompt="current prompt",
        reply="current reply",
    )
    memory.append_user_memory(
        event,
        session_key="older",
        prompt="older prompt",
        reply="older reply",
    )

    assert memory.get_user_memory(
        event,
        current_session_key="current",
        has_short_history=True,
    ) == [
        {"role": "user", "content": "older prompt"},
        {"role": "assistant", "content": "older reply"},
    ]
