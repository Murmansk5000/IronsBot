import asyncio
from collections.abc import Awaitable, Callable

import nonebot
import pytest
from pytest import MonkeyPatch

from ironsbot.config.models.ai import AiConfig
from ironsbot.core.features import FeatureConfig
from ironsbot.services.ai.history import HistoryMessage
from ironsbot.services.ai.responses import AiResponseResult
from ironsbot.services.ai.service import REQUEST_FAILED_REPLY, AiService
from ironsbot.services.messaging.admin_notice import AdminNoticeService
from tests.helpers.ai import FakeAiCompletionClient
from tests.helpers.onebot_events import group_message_event
from tests.helpers.runtime import build_test_runtime

GROUP_ID = 456
USER_ID = 123
CompletionRequester = Callable[
    [AiConfig, list[HistoryMessage]],
    Awaitable[AiResponseResult],
]

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

onebot_context = pytest.importorskip("ironsbot.runtime.onebot_context")


class FakeBot:
    async def get_group_info(
        self,
        *,
        group_id: int,
        no_cache: bool = False,
    ) -> dict[str, object]:
        assert no_cache is False
        return {"group_id": group_id, "group_name": "示例群"}


async def _successful_completion(
    _config: AiConfig,
    _messages: list[HistoryMessage],
) -> AiResponseResult:
    return AiResponseResult(status_code=200, reply="正常回复")


def _ai_service(
    *,
    admin_groups: tuple[int, ...] = (),
    superusers: tuple[int, ...] = (),
    request_completion: CompletionRequester = _successful_completion,
) -> AiService:
    config = AiConfig(api_key="test-key", memory=False)
    runtime = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy={
                str(group_id): ["admin_notice"] for group_id in admin_groups
            },
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
            user_id=USER_ID,
            group_id=GROUP_ID,
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
            user_id=USER_ID,
            group_id=GROUP_ID,
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
            user_id=USER_ID,
            group_id=GROUP_ID,
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
            {},
            bot=FakeBot(),
        )
    )

    assert f"群：示例群（{GROUP_ID}）" in source
    assert f"用户：{USER_ID}（群名片）" in source
    assert "消息ID：33" in source
    assert "消息：你好" in source


def test_ai_notice_source_context_falls_back_to_group_alias() -> None:
    event = group_message_event("hello", group_id=GROUP_ID)

    async def fail_group_info(**_kwargs: object) -> dict[str, object]:
        raise RuntimeError("boom")

    class FailingBot:
        get_group_info = staticmethod(fail_group_info)

    source = asyncio.run(
        onebot_context.build_notice_source(
            event,
            "你好",
            {"example": GROUP_ID},
            bot=FailingBot(),
        )
    )

    assert f"群：example（{GROUP_ID}）" in source


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
            user_id=USER_ID,
            group_id=GROUP_ID,
            prompt="hello",
            source_context="群：456",
        )

    assert len(sent) == 1
    assert "触发来源：\n群：456" in sent[0]
