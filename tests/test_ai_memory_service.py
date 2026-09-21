import asyncio
from collections.abc import Callable
from pathlib import Path

from pytest import MonkeyPatch

from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    OfficialUnionIdentity,
    Platform,
)
from ironsbot.integrations.storage.ai_memory import SqliteAiMemoryStore
from ironsbot.services.ai.memory import AiMemoryTurn
from ironsbot.services.identity_principals import IdentityPrincipalService

GROUP_ID = 456
USER_ID = 123
ACTOR = ActorRef(Platform.ONEBOT, str(USER_ID))
CONVERSATION = ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))


def _append(
    store: SqliteAiMemoryStore,
    session_key: str,
    prompt: str,
    reply: str,
) -> None:
    asyncio.run(
        store.append(
            AiMemoryTurn(
                ACTOR,
                session_key,
                CONVERSATION,
                prompt,
                reply,
            )
        )
    )


def test_ai_memory_appends_and_reads_recent_turn(tmp_path: Path) -> None:
    store = SqliteAiMemoryStore(tmp_path / "memory.sqlite")
    _append(store, "session-a", "first prompt", "first reply")
    _append(store, "session-b", "second prompt", "second reply")

    assert asyncio.run(
        store.load(
            actor=ACTOR,
            current_session_key="current",
            exclude_current_session=False,
            limit=2,
        )
    ) == [
        {"role": "user", "content": "second prompt"},
        {"role": "assistant", "content": "second reply"},
    ]


def test_ai_memory_excludes_current_short_history_session(tmp_path: Path) -> None:
    store = SqliteAiMemoryStore(tmp_path / "memory.sqlite")
    _append(store, "current", "current prompt", "current reply")
    _append(store, "older", "older prompt", "older reply")

    assert asyncio.run(
        store.load(
            actor=ACTOR,
            current_session_key="current",
            exclude_current_session=True,
            limit=2,
        )
    ) == [
        {"role": "user", "content": "older prompt"},
        {"role": "assistant", "content": "older reply"},
    ]


def test_ai_memory_keeps_official_platform_identity_opaque(tmp_path: Path) -> None:
    store = SqliteAiMemoryStore(tmp_path / "memory.sqlite")
    actor = ActorRef(Platform.QQ_OFFICIAL, "openid-example")
    conversation = ConversationRef(Platform.QQ_OFFICIAL, "guild", "guild-example")
    asyncio.run(
        store.append(
            AiMemoryTurn(
                actor,
                "official-session",
                conversation,
                "official prompt",
                "official reply",
            )
        )
    )

    assert asyncio.run(
        store.load(
            actor=actor,
            current_session_key="current",
            exclude_current_session=False,
            limit=2,
        )
    ) == [
        {"role": "user", "content": "official prompt"},
        {"role": "assistant", "content": "official reply"},
    ]


def test_ai_memory_is_shared_by_union_principal_across_apps(tmp_path: Path) -> None:
    principals = IdentityPrincipalService()
    store = SqliteAiMemoryStore(
        tmp_path / "memory.sqlite",
        principal_for=principals.actor_principal,
    )
    actor_a = ActorRef(Platform.QQ_OFFICIAL, "user-a", account_id="app-a")
    actor_b = ActorRef(Platform.QQ_OFFICIAL, "user-b", account_id="app-b")
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        "user-a",
        account_id="app-a",
    )
    asyncio.run(
        store.append(
            AiMemoryTurn(actor_a, "session-a", conversation, "prompt", "reply")
        )
    )
    for actor in (actor_a, actor_b):
        for merge in principals.observe_union_identity(
            actor=actor,
            evidence=OfficialUnionIdentity("shared-union"),
        ):
            store.merge_principals(merge.source, merge.target)

    assert asyncio.run(
        store.load(
            actor=actor_b,
            current_session_key="session-b",
            exclude_current_session=False,
            limit=2,
        )
    ) == [
        {"role": "user", "content": "prompt"},
        {"role": "assistant", "content": "reply"},
    ]


def test_ai_memory_runs_sqlite_operations_in_a_worker_thread(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    async def fake_to_thread(
        function: Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        calls.append(getattr(function, "__name__", ""))
        return function(*args, **kwargs)

    monkeypatch.setattr(
        "ironsbot.integrations.storage.ai_memory.asyncio.to_thread",
        fake_to_thread,
    )
    store = SqliteAiMemoryStore(tmp_path / "memory.sqlite")

    _append(store, "session", "prompt", "reply")
    assert asyncio.run(
        store.load(
            actor=ACTOR,
            current_session_key="current",
            exclude_current_session=False,
            limit=2,
        )
    ) == [
        {"role": "user", "content": "prompt"},
        {"role": "assistant", "content": "reply"},
    ]
    assert calls == ["_append", "_load"]
