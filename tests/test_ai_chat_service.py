import asyncio
from collections.abc import Awaitable, Callable

import nonebot
import pytest
from pytest import MonkeyPatch

from ironsbot.config.models.ai import AiConfig
from ironsbot.config.models.features import FeatureConfig
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.services.ai.history import HistoryMessage
from ironsbot.services.ai.memory import AiMemoryTurn
from ironsbot.services.ai.responses import AiResponseResult
from ironsbot.services.ai.service import REQUEST_FAILED_REPLY, AiService
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from tests.helpers.ai import FakeAiCompletionClient
from tests.helpers.onebot_events import group_message_event
from tests.helpers.runtime import build_test_runtime

GROUP_ID = 456
USER_ID = 123
ACTOR = ActorRef(Platform.ONEBOT, str(USER_ID))
CONVERSATION = ConversationRef(Platform.ONEBOT, "group", str(GROUP_ID))
CompletionRequester = Callable[
    [AiConfig, list[HistoryMessage]],
    Awaitable[AiResponseResult],
]

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

onebot_context = pytest.importorskip("ironsbot.integrations.onebot.context")


class FakeBot:
    async def get_group_info(
        self,
        *,
        group_id: int,
        no_cache: bool = False,
    ) -> dict[str, object]:
        assert no_cache is False
        return {"group_id": group_id, "group_name": "示例群"}


class RecordingMemory:
    def __init__(self) -> None:
        self.loads: list[tuple[ActorRef, str, bool, int]] = []
        self.turns: list[AiMemoryTurn] = []

    async def load(
        self,
        *,
        actor: ActorRef,
        current_session_key: str,
        exclude_current_session: bool,
        limit: int,
    ) -> list[HistoryMessage]:
        self.loads.append((actor, current_session_key, exclude_current_session, limit))
        return [{"role": "user", "content": "memory prompt"}]

    async def append(self, turn: AiMemoryTurn) -> None:
        self.turns.append(turn)


async def _successful_completion(
    _config: AiConfig,
    _messages: list[HistoryMessage],
) -> AiResponseResult:
    return AiResponseResult(status_code=200, reply="正常回复")


@pytest.mark.asyncio
async def test_ai_chat_awaits_memory_store_reads_and_writes() -> None:
    config = AiConfig(
        api_key="test-key",
        memory=True,
        memory_turns=2,
        memory_max_chars=100,
    )
    runtime = build_test_runtime()
    memory = RecordingMemory()
    service = AiService(
        config,
        runtime.features,
        runtime.admin_notices,
        ("战队",),
        FakeAiCompletionClient(config, _successful_completion),
        memory,
    )

    assert await service.chat_reply(
        actor=ACTOR,
        conversation=CONVERSATION,
        prompt="hello",
    ) == "正常回复"
    assert len(memory.loads) == 1
    actor, session_key, exclude_current_session, limit = memory.loads[0]
    assert actor == ACTOR
    assert exclude_current_session is False
    assert limit == config.memory_turns * 2
    assert memory.turns == [
        AiMemoryTurn(
            ACTOR,
            session_key,
            CONVERSATION,
            "hello",
            "正常回复",
        )
    ]


def _ai_service(
    *,
    admin_groups: tuple[int, ...] = (),
    superusers: tuple[int, ...] = (),
    request_completion: CompletionRequester = _successful_completion,
) -> AiService:
    config = AiConfig(api_key="test-key", memory=False)
    runtime = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={str(group_id): ["admin_notice"] for group_id in admin_groups},
        ),
        superuser_ids=superusers,
    )
    return AiService(
        config,
        runtime.features,
        runtime.admin_notices,
        ("战队",),
        FakeAiCompletionClient(config, request_completion),
    )


async def _failed_completion(
    _config: AiConfig,
    _messages: list[HistoryMessage],
) -> AiResponseResult:
    return AiResponseResult(
        status_code=500,
        error_kind="http",
        error_title="接口返回异常",
        error_detail="boom",
    )


@pytest.mark.asyncio
async def test_ai_error_is_visible_to_superuser() -> None:
    service = _ai_service(
        superusers=(USER_ID,),
        request_completion=_failed_completion,
    )

    assert (
        await service.chat_reply(
            actor=ACTOR,
            conversation=CONVERSATION,
            prompt="hello",
        )
        == REQUEST_FAILED_REPLY
    )


@pytest.mark.asyncio
async def test_ai_error_is_visible_in_admin_notice_group() -> None:
    service = _ai_service(
        admin_groups=(GROUP_ID,),
        request_completion=_failed_completion,
    )

    assert (
        await service.chat_reply(
            actor=ACTOR,
            conversation=CONVERSATION,
            prompt="hello",
        )
        == REQUEST_FAILED_REPLY
    )


@pytest.mark.asyncio
async def test_ai_error_is_silent_in_regular_group() -> None:
    service = _ai_service(
        request_completion=_failed_completion,
    )

    assert (
        await service.chat_reply(
            actor=ACTOR,
            conversation=CONVERSATION,
            prompt="hello",
        )
        is None
    )


def test_ai_notice_source_context_includes_group_user_and_message() -> None:
    event = group_message_event(
        "hello",
        user_id=USER_ID,
        group_id=GROUP_ID,
        message_id=33,
        sender={"card": "群名片"},
    )

    source = asyncio.run(
        onebot_context.build_notice_source(
            event,
            "你好",
            bot=FakeBot(),
        )
    )

    assert f"群：示例群（{GROUP_ID}）" in source
    assert f"用户：{USER_ID}（群名片）" in source
    assert "消息ID：33" in source
    assert "消息：你好" in source


def test_ai_notice_source_context_falls_back_to_group_id() -> None:
    event = group_message_event("hello", group_id=GROUP_ID)

    async def fail_group_info(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("boom")

    class FailingBot:
        get_group_info = staticmethod(fail_group_info)

    source = asyncio.run(
        onebot_context.build_notice_source(
            event,
            "你好",
            bot=FailingBot(),
        )
    )

    assert f"群：{GROUP_ID}" in source
    assert "example" not in source


@pytest.mark.asyncio
async def test_ai_admin_notice_includes_source_and_is_limited(
    monkeypatch: MonkeyPatch,
) -> None:
    sent: list[str] = []

    async def fake_send(
        _service: AdminNoticeService,
        message: str,
        **_kwargs: object,
    ) -> None:
        sent.append(message)

    monkeypatch.setattr(AdminNoticeService, "send", fake_send)
    service = _ai_service(
        request_completion=_failed_completion,
    )
    for _ in range(2):
        await service.chat_reply(
            actor=ACTOR,
            conversation=CONVERSATION,
            prompt="hello",
            source_context="群：456",
        )

    assert len(sent) == 1
    assert "触发来源：\n群：456" in sent[0]
