import asyncio

import nonebot
import pytest
from pytest import MonkeyPatch

from ironsbot.config.models.ai import AiConfig
from ironsbot.services.ai.resources import AiResources
from tests.helpers.onebot_events import group_message_event

GROUP_ID = 456
USER_ID = 123


try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

service = pytest.importorskip("ironsbot.services.ai.chat")
constants = pytest.importorskip("ironsbot.services.ai.constants")
ai_client = pytest.importorskip("ironsbot.services.ai.client")
ai_resources_module = pytest.importorskip("ironsbot.services.ai.resources")
source_context = pytest.importorskip("ironsbot.services.ai.source_context")


class FakeBot:
    async def get_group_info(
        self,
        *,
        group_id: int,
        no_cache: bool = False,
    ) -> dict[str, object]:
        assert no_cache is False
        return {"group_id": group_id, "group_name": "示例群"}


def _ai_resources(
    group_aliases: dict[str, int] | None = None,
) -> AiResources:
    return AiResources(
        AiConfig(),
        "test-key",
        group_aliases or {},
        ("战队",),
        20,
    )


def test_can_show_admin_notice_for_superuser(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(service, "is_superuser", lambda user_id: user_id == USER_ID)
    monkeypatch.setattr(service, "group_has_feature", lambda *_args: False)

    assert service.can_show_admin_notice(
        group_message_event(user_id=USER_ID, group_id=GROUP_ID)
    )


def test_can_show_admin_notice_for_admin_notice_group(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "is_superuser", lambda _user_id: False)
    monkeypatch.setattr(
        service,
        "group_has_feature",
        lambda group_id, feature: group_id == GROUP_ID and feature == "admin_notice",
    )

    assert service.can_show_admin_notice(
        group_message_event(user_id=USER_ID, group_id=GROUP_ID)
    )


def test_can_hide_admin_notice_for_regular_group(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(service, "is_superuser", lambda _user_id: False)
    monkeypatch.setattr(service, "group_has_feature", lambda *_args: False)

    assert not service.can_show_admin_notice(
        group_message_event(user_id=USER_ID, group_id=GROUP_ID)
    )


def test_ai_error_reply_detection() -> None:
    assert service.is_ai_error_reply(constants.REQUEST_FAILED_REPLY)
    assert service.is_ai_error_reply(constants.EMPTY_REPLY)
    assert not service.is_ai_error_reply("正常回复")


def test_ai_notice_source_context_includes_group_user_and_message() -> None:
    event = group_message_event(
        "hello",
        user_id=USER_ID,
        group_id=GROUP_ID,
        message_id=33,
        sender={"card": "群名片"},
    )

    source = asyncio.run(
        source_context.build_notice_source(
            event,
            "你好",
            _ai_resources(),
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
        source_context.build_notice_source(
            event,
            "你好",
            _ai_resources({"example": GROUP_ID}),
            bot=FailingBot(),
        )
    )

    assert f"群：example（{GROUP_ID}）" in source


def test_ai_client_notice_appends_source_context() -> None:
    message = source_context.append_ai_notice_source_context(
        "AI聊天接口异常。",
        "群：456",
    )

    assert message == "AI聊天接口异常。\n\n触发来源：\n群：456"


def test_ai_admin_notice_is_limited_by_key(monkeypatch: MonkeyPatch) -> None:
    sent: list[str] = []

    async def fake_send(message: str, **_kwargs: object) -> None:
        sent.append(message)

    monkeypatch.setattr(ai_resources_module, "send_admin_notice", fake_send)
    resources = _ai_resources()
    asyncio.run(resources.notify_admin_once("same", "first"))
    asyncio.run(resources.notify_admin_once("same", "second"))

    assert sent == ["first"]
