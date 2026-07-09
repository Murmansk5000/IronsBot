from pathlib import Path
from types import SimpleNamespace

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from pytest import MonkeyPatch

from ironsbot.services.ai import memory

GROUP_ID = 456
USER_ID = 123


def _group_event(text: str = "hello") -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=USER_ID,
        message_type="group",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        group_id=GROUP_ID,
        sender={},
    )


def _enable_memory(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        memory,
        "_get_ai_config",
        lambda: SimpleNamespace(
            memory=True,
            memory_path=tmp_path / "memory.sqlite",
            memory_turns=1,
            memory_max_chars=200,
        ),
    )


def test_ai_memory_appends_and_reads_recent_turn(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    _enable_memory(monkeypatch, tmp_path)
    event = _group_event()

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
    event = _group_event()

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
