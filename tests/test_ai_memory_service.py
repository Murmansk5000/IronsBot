from pathlib import Path

from ironsbot.config.models.ai import AiConfig
from ironsbot.services.ai import memory
from tests.helpers.onebot_events import group_message_event

GROUP_ID = 456
USER_ID = 123


def _memory_config(tmp_path: Path) -> AiConfig:
    return AiConfig(
        memory_path=tmp_path / "memory.sqlite",
        memory_turns=1,
        memory_max_chars=200,
    )


def test_ai_memory_appends_and_reads_recent_turn(
    tmp_path: Path,
) -> None:
    config = _memory_config(tmp_path)
    event = group_message_event(user_id=USER_ID, group_id=GROUP_ID)

    memory.append_user_memory(
        config,
        event,
        session_key="session-a",
        prompt="first prompt",
        reply="first reply",
    )
    memory.append_user_memory(
        config,
        event,
        session_key="session-b",
        prompt="second prompt",
        reply="second reply",
    )

    assert memory.get_user_memory(
        config,
        event,
        current_session_key="current",
        has_short_history=False,
    ) == [
        {"role": "user", "content": "second prompt"},
        {"role": "assistant", "content": "second reply"},
    ]


def test_ai_memory_excludes_current_short_history_session(
    tmp_path: Path,
) -> None:
    config = _memory_config(tmp_path)
    event = group_message_event(user_id=USER_ID, group_id=GROUP_ID)

    memory.append_user_memory(
        config,
        event,
        session_key="current",
        prompt="current prompt",
        reply="current reply",
    )
    memory.append_user_memory(
        config,
        event,
        session_key="older",
        prompt="older prompt",
        reply="older reply",
    )

    assert memory.get_user_memory(
        config,
        event,
        current_session_key="current",
        has_short_history=True,
    ) == [
        {"role": "user", "content": "older prompt"},
        {"role": "assistant", "content": "older reply"},
    ]
