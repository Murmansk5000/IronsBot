from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.integrations.storage.push_topics import SqlitePushTopicStore
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliverySummary,
    ProactiveMessageDelivery,
)
from ironsbot.services.messaging.topic_commands import build_topic_operations
from ironsbot.services.messaging.topics import PushTopicService, TopicPublication

GROUP = ConversationRef(Platform.ONEBOT, "group", "10001")
OWNER = ActorRef(Platform.ONEBOT, "20001")
MEMBER = ActorRef(Platform.ONEBOT, "20002")


class Delivery:
    def __init__(self) -> None:
        self.calls: list[ConversationRef] = []
        self.fail = False

    async def send(
        self,
        message: OutboundMessage,
        targets: tuple[ConversationRef, ...],
        *,
        action_name: str,
        subscription_key: str,
    ) -> ProactiveDeliverySummary:
        assert message.parts and action_name and subscription_key
        self.calls.extend(targets)
        return (
            ProactiveDeliverySummary((), (), targets)
            if self.fail
            else ProactiveDeliverySummary(targets, ())
        )


def service(tmp_path: Path) -> tuple[PushTopicService, Delivery]:
    delivery = Delivery()
    features = FeatureService(
        {GROUP: frozenset({"push_topics"})}, {}, frozenset({OWNER})
    )
    topics = PushTopicService(
        SqlitePushTopicStore(tmp_path / "topics.sqlite"),
        cast("ProactiveMessageDelivery", delivery),
        PushUnsubscribeStore(tmp_path / "subscriptions.sqlite"),
        features,
    )
    topics.create("公告", "群公告")
    return topics, delivery


@pytest.mark.asyncio
async def test_topic_opt_in_td_and_persistent_dedup(tmp_path: Path) -> None:
    topics, delivery = service(tmp_path)
    publication = TopicPublication(OutboundMessage((TextPart("内容"),)), "same-event")
    assert await topics.publish("公告", publication) == {}
    topics.subscribe("公告", GROUP, enabled=True)
    assert await topics.publish("公告", publication) == {"delivered": 1}
    assert await topics.publish("公告", publication) == {"duplicate": 1}
    assert delivery.calls == [GROUP]
    topics.subscribe("公告", GROUP, enabled=False)
    assert (
        await topics.publish("公告", TopicPublication(publication.message, "another"))
        == {}
    )
    assert (
        SqlitePushTopicStore(tmp_path / "topics.sqlite").history("公告")[0].status
        == "delivered"
    )


@pytest.mark.asyncio
async def test_old_receiptless_failures_are_not_blindly_retried(tmp_path: Path) -> None:
    topics, delivery = service(tmp_path)
    delivery.fail = True
    topics.subscribe("公告", GROUP, enabled=True)
    publication = TopicPublication(OutboundMessage((TextPart("内容"),)), "uncertain")
    assert await topics.publish("公告", publication) == {"uncertain": 1}
    assert await topics.publish("公告", publication) == {"duplicate": 1}


@pytest.mark.asyncio
async def test_permissions_are_checked_only_for_claimed_topic_input(
    tmp_path: Path,
) -> None:
    topics, _ = service(tmp_path)
    context = MessageInputContext(
        IncomingMessageRef(Platform.ONEBOT, MEMBER, GROUP, "message", "订阅公告"),
        mentions_bot=False,
    )
    regular = build_topic_operations(topics)
    result = await regular["messaging.topic.subscribe"]("订阅公告", context)
    assert isinstance(result, OutboundMessage)
    assert "仅群主和管理员" in str(result.parts)
    allowed = build_topic_operations(topics)
    context = replace(context, message=replace(context.message, group_role="admin"))
    result = await allowed["messaging.topic.subscribe"]("订阅公告", context)
    assert GROUP in topics.store.subscribers("公告")
    denied = await allowed["messaging.topic.create"]("推送新建 测试 测试主题", context)
    assert isinstance(denied, OutboundMessage)
    assert "仅限超级管理员" in str(denied.parts)


def test_native_unclaimed_chat_does_not_reach_topic_permissions(tmp_path: Path) -> None:
    from inspect import isfunction
    from types import SimpleNamespace

    from ironsbot.plugins.onebot.messaging.topics import install_topic_commands
    from tests.helpers.onebot_events import group_message_event

    topics, _ = service(tmp_path)
    rules: list[Any] = []

    class Registry:
        def priority(self, _name: str) -> int:
            return 5

        def on_message(self, **kwargs: Any) -> Any:
            rules.append(kwargs["rule"])
            return SimpleNamespace(append_handler=lambda _handler: None)

    install_topic_commands(
        cast("Any", Registry()), cast("Any", SimpleNamespace(topics=topics))
    )
    predicate = next(
        checker.call
        for checker in rules[0].checkers
        if isfunction(checker.call) and checker.call.__name__ == "matches"
    )
    assert not predicate(group_message_event(text="普通闲聊"))
    assert predicate(group_message_event(text="推送新建 公告 群公告"))
