from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest

from ironsbot.config.models.messaging import PushUnsubscribeConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import (
    DeliveryCapabilities,
    DeliveryFailureKind,
    OutboundMessage,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.core.push_routing import PushRouteDecision
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.integrations.storage.push_topics import SqlitePushTopicStore
from ironsbot.services.messaging.proactive_delivery import (
    ProactiveDeliveryPolicy,
    ProactiveMessageDelivery,
)
from ironsbot.services.messaging.topic_commands import (
    build_topic_operations,
    parse_topic_command,
    topic_command_contracts,
)
from ironsbot.services.messaging.topics import (
    PushTopicService,
    TopicPublication,
    TopicSchedule,
)
from ironsbot.services.private_conversation_routes import PrivateConversationRoutes

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.outbound import ReplyContext
    from ironsbot.services.messaging.topic_models import PushTopic

GROUP = ConversationRef(Platform.ONEBOT, "group", "10001")
OTHER = ConversationRef(Platform.ONEBOT, "group", "10002")
OWNER = ActorRef(Platform.ONEBOT, "20001")
MEMBER = ActorRef(Platform.ONEBOT, "20002")
SCHEDULE_COUNT = 3
HISTORY_LIMIT = 500


@dataclass
class Messenger:
    results: list[SendResult] = field(default_factory=list)
    calls: list[ConversationRef] = field(default_factory=list)

    def capabilities_for(self, conversation: ConversationRef) -> DeliveryCapabilities:
        assert conversation.kind in {"private", "group"}
        return DeliveryCapabilities(
            can_reply_to_event=True,
            can_send_proactively=True,
            can_mention_members=True,
            supports_group_context=True,
            supports_private_context=True,
            supports_images=True,
        )

    async def send(
        self, conversation: ConversationRef, message: OutboundMessage
    ) -> SendResult:
        assert message.parts
        self.calls.append(conversation)
        return (
            self.results.pop(0)
            if self.results
            else SendResult(
                delivered=True,
                message_id=f"sent-{len(self.calls)}",
            )
        )

    async def reply(
        self, context: ReplyContext, message: OutboundMessage
    ) -> SendResult:
        return await self.send(context.conversation, message)


@dataclass
class Job:
    id: str


class Scheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.options: dict[str, dict[str, Any]] = {}

    def add_job(self, func: Any, trigger: str, **kwargs: Any) -> Job:
        job = Job(kwargs["id"])
        self.jobs[job.id] = job
        self.options[job.id] = {"func": func, "trigger": trigger, **kwargs}
        return job

    def get_jobs(self) -> list[Job]:
        return list(self.jobs.values())

    def remove_job(self, job_id: str) -> None:
        del self.jobs[job_id]


def make_service(
    tmp_path: Path, *, messenger: Messenger | None = None
) -> PushTopicService:
    features = FeatureService(
        group_features={
            GROUP: frozenset({"push_topics"}),
            OTHER: frozenset({"push_topics"}),
        },
        actor_features={},
        superusers=frozenset({OWNER}),
    )
    subscriptions = PushUnsubscribeStore(tmp_path / "state.sqlite")
    delivery = ProactiveMessageDelivery(
        messenger or Messenger(),
        features,
        PromotionCatalog({}),
        subscriptions,
        PushUnsubscribeConfig(),
        policy=ProactiveDeliveryPolicy(retry_delay_seconds=0),
    )
    return PushTopicService(
        SqlitePushTopicStore(tmp_path / "state.sqlite"),
        delivery,
        subscriptions,
        features,
    )


def context(
    text: str,
    actor: ActorRef = OWNER,
    *,
    role: str | None = None,
    conversation: ConversationRef = GROUP,
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            platform=actor.platform,
            actor=actor,
            conversation=conversation,
            message_id="message-1",
            text=text,
            group_role=role,
        ),
        mentions_bot=False,
    )


def text_of(message: object) -> str:
    assert isinstance(message, OutboundMessage)
    return "".join(part.text for part in message.parts if isinstance(part, TextPart))


@pytest.mark.asyncio
async def test_opt_in_delivery_td_and_restart(tmp_path: Path) -> None:
    messenger = Messenger()
    service = make_service(tmp_path, messenger=messenger)
    service.create("公告", "群公告")
    publication = TopicPublication(OutboundMessage.from_text("hello"), "news-1")
    assert await service.publish("公告", publication) == {}
    service.subscribe("公告", GROUP, enabled=True)
    assert await service.publish("公告", publication) == {"delivered": 1}
    assert await service.publish("公告", publication) == {"duplicate": 1}
    assert messenger.calls == [GROUP]
    restored = make_service(tmp_path, messenger=messenger)
    await restored.start(Scheduler())
    assert await restored.publish("公告", publication) == {"duplicate": 1}
    service.subscribe("公告", GROUP, enabled=False)
    assert service.subscription_options(GROUP)[0].unsubscribed
    assert (
        await service.publish("公告", TopicPublication(publication.message, "news-2"))
        == {}
    )
    assert service.store.history("公告")[0].status == "delivered"


@pytest.mark.asyncio
async def test_uncertain_not_retried_and_other_target_continues(tmp_path: Path) -> None:
    messenger = Messenger(
        results=[
            SendResult(
                delivered=False,
                error_code="uncertain",
                failure_kind=DeliveryFailureKind.UNCERTAIN,
            )
        ]
    )
    service = make_service(tmp_path, messenger=messenger)
    service.create("news", "News")
    for target in (GROUP, OTHER):
        service.subscribe("news", target, enabled=True)
    publication = TopicPublication(OutboundMessage.from_text("hello"), "key")
    assert await service.publish("news", publication) == {
        "uncertain": 1,
        "delivered": 1,
    }
    assert await service.publish("news", publication) == {"duplicate": 2}
    assert messenger.calls == [GROUP, OTHER]


@pytest.mark.asyncio
async def test_definite_failure_can_retry_but_concurrent_success_cannot(
    tmp_path: Path,
) -> None:
    messenger = Messenger(
        results=[
            SendResult(
                delivered=False,
                error_code="failed",
                failure_kind=DeliveryFailureKind.PERMANENT,
            )
        ]
    )
    service = make_service(tmp_path, messenger=messenger)
    service.create("news", "News")
    service.subscribe("news", GROUP, enabled=True)
    publication = TopicPublication(OutboundMessage.from_text("hello"), "key")
    assert await service.publish("news", publication) == {"failed": 1}
    results = await asyncio.gather(
        *(service.publish("news", publication) for _ in range(3))
    )
    assert results == [{"delivered": 1}, {"duplicate": 1}, {"duplicate": 1}]


@pytest.mark.asyncio
async def test_feature_revocation_and_blacklist_block_direct_send(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.create("news", "News")
    denied = ConversationRef(Platform.ONEBOT, "group", "10003")
    assert (
        await service.publish(
            "news",
            TopicPublication(OutboundMessage.from_text("hello")),
            targets=(denied,),
        )
        == {}
    )
    assert not service.store.history("news")


@pytest.mark.asyncio
async def test_schedule_disable_enable_restart_and_code_owned_delete(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    scheduler = Scheduler()

    async def provider() -> TopicPublication:
        return TopicPublication(OutboundMessage.from_text("scheduled"), "provider-key")

    schedules = (
        TopicSchedule("interval", "interval", provider, {"minutes": 5}),
        TopicSchedule("cron", "cron", provider, {"hour": 12}),
        TopicSchedule(
            "expired",
            "date",
            provider,
            {
                "run_date": datetime.now(timezone.utc) - timedelta(hours=1),
            },
        ),
        TopicSchedule(
            "future",
            "date",
            provider,
            {
                "run_date": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        ),
    )
    await service.register("news", "News", schedules)
    await service.start(scheduler)
    assert len(scheduler.jobs) == SCHEDULE_COUNT
    await service.start(scheduler)
    assert len(scheduler.jobs) == SCHEDULE_COUNT
    assert all(
        job["coalesce"] and job["max_instances"] == 1
        for job in scheduler.options.values()
    )
    await service.set_enabled("news", enabled=False)
    assert scheduler.jobs == {}
    await service.set_enabled("news", enabled=True)
    assert len(scheduler.jobs) == SCHEDULE_COUNT
    with pytest.raises(ValueError, match="程序注册"):
        await service.delete("news")
    await service.stop()
    assert scheduler.jobs == {}


@pytest.mark.asyncio
async def test_commands_roles_and_no_subscription_command_theft(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    operations = build_topic_operations(service)
    command = operations["messaging.topic.create"]
    assert "超级管理员" in text_of(
        await command(
            "推送新建 公告 群公告",
            context(
                "",
                MEMBER,
                role="admin",
            ),
        )
    )
    assert "已创建" in text_of(await command("推送新建 公告 群公告", context("")))
    subscribe = operations["messaging.topic.subscribe"]
    assert "群主和管理员" in text_of(await subscribe("订阅公告", context("", MEMBER)))
    assert "已订阅" in text_of(
        await subscribe("订阅公告", context("", MEMBER, role="admin"))
    )
    assert parse_topic_command("订阅战队12345", service.known_keys) is None
    assert parse_topic_command("退订全部", service.known_keys) is None
    assert parse_topic_command("今天讨论推送公告", service.known_keys) is None
    assert parse_topic_command("订阅主题 公告", service.known_keys) is not None
    assert len(topic_command_contracts(service)) == len(operations)


@pytest.mark.asyncio
async def test_direct_command_authorization_and_explicit_endpoint(
    tmp_path: Path,
) -> None:
    messenger = Messenger()
    service = make_service(tmp_path, messenger=messenger)
    service.create("news", "News")
    service.resolve_target = lambda value, _source: (
        (OTHER,) if value == "群:test" else ()
    )
    operation = build_topic_operations(service)["messaging.topic.direct"]
    assert "超级管理员" in text_of(
        await operation(
            "推送直发 news 群:test hello",
            context("", MEMBER, role="owner"),
        )
    )
    assert not messenger.calls
    assert "明确目标" in text_of(
        await operation(
            "推送直发 news 群:unknown hello",
            context(""),
        )
    )
    assert not messenger.calls
    assert "delivered=1" in text_of(
        await operation(
            "推送直发 news 群:test hello",
            context(""),
        )
    )
    assert messenger.calls == [OTHER]
    service.subscribe("news", OTHER, enabled=False)
    assert "无符合条件" in text_of(
        await operation(
            "推送直发 news 群:test hello",
            context(""),
        )
    )


@pytest.mark.asyncio
async def test_delivery_exception_is_uncertain_and_next_target_survives(
    tmp_path: Path,
) -> None:
    class BrokenMessenger(Messenger):
        async def send(
            self, conversation: ConversationRef, message: OutboundMessage
        ) -> SendResult:
            if conversation == GROUP:
                self.calls.append(conversation)
                raise ConnectionError
            return await super().send(conversation, message)

    messenger = BrokenMessenger()
    service = make_service(tmp_path, messenger=messenger)
    service.create("news", "News")
    service.subscribe("news", GROUP, enabled=True)
    service.subscribe("news", OTHER, enabled=True)
    publication = TopicPublication(OutboundMessage.from_text("test"), "event")
    assert await service.publish("news", publication) == {
        "uncertain": 1,
        "delivered": 1,
    }
    assert await service.publish("news", publication) == {"duplicate": 2}


@pytest.mark.asyncio
async def test_scheduled_provider_publishes_and_disabled_provider_does_not_run(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    calls: list[str] = []

    async def provider() -> TopicPublication:
        calls.append("called")
        return TopicPublication(OutboundMessage.from_text("test"), "event")

    await service.register(
        "news",
        "News",
        (
            TopicSchedule(
                "daily",
                "cron",
                provider,
                {"hour": 12},
            ),
        ),
    )
    service.subscribe("news", GROUP, enabled=True)
    scheduler = Scheduler()
    await service.start(scheduler)
    run = scheduler.options["push_topic:news:daily"]["func"]
    await run()
    assert service.store.history("news")[0].status == "delivered"
    await service.set_enabled("news", enabled=False)
    await run()
    assert calls == ["called"]


@pytest.mark.asyncio
async def test_database_work_is_off_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    service = make_service(tmp_path)
    store = service.store
    event_thread = threading.get_ident()
    threads: list[int] = []
    original = store.topics

    def checked_topics() -> tuple[PushTopic, ...]:
        threads.append(threading.get_ident())
        return original()

    monkeypatch.setattr(store, "topics", checked_topics)
    operation = build_topic_operations(service)["messaging.topic.create"]
    assert "已创建" in text_of(await operation("推送新建 news News", context("")))
    await service.start(Scheduler())
    await service.set_enabled("news", enabled=False)
    await service.delete("news")
    assert threads and all(thread != event_thread for thread in threads)


@pytest.mark.asyncio
async def test_shared_sqlite_namespaces_do_not_overwrite_existing_preferences(
    tmp_path: Path,
) -> None:
    service = make_service(tmp_path)
    service.subscriptions.unsubscribe(GROUP, "existing-key", "text_push")
    service.create("news", "News")
    service.subscribe("news", GROUP, enabled=True)
    assert service.subscriptions.is_unsubscribed(GROUP, "existing-key")
    with SqlitePushTopicStore(tmp_path / "state.sqlite").database.connect() as db:
        names = {
            row[0]
            for row in db.execute(
                "SELECT namespace FROM ironsbot_schema_migrations",
            )
        }
        assert "push_topics" in names
        assert names - {"push_topics"}


@pytest.mark.asyncio
async def test_duplicate_logical_routes_share_actual_destination_claim(
    tmp_path: Path,
) -> None:
    messenger = Messenger()
    service = make_service(tmp_path, messenger=messenger)
    service.delivery = replace(
        service.delivery,
        private_routes=PrivateConversationRoutes(
            group_route=lambda _target: PushRouteDecision("ready", OTHER),
        ),
    )
    service.create("news", "News")
    service.subscribe("news", GROUP, enabled=True)
    service.subscribe("news", OTHER, enabled=True)
    publication = TopicPublication(OutboundMessage.from_text("event"), "unique")
    assert await service.publish("news", publication) == {"delivered": 1}
    assert messenger.calls == [OTHER]
    assert await service.publish("news", publication) == {"duplicate": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", [Platform.ONEBOT, Platform.QQ_OFFICIAL])
async def test_private_subscription_is_only_current_conversation(
    tmp_path: Path, platform: Platform
) -> None:
    actor = ActorRef(platform, "private-actor", account_id="application")
    target = ConversationRef(platform, "private", actor.id, account_id=actor.account_id)
    features = FeatureService({}, {actor: frozenset({"push_topics"})}, frozenset())
    service = make_service(tmp_path)
    service.features = features
    service.create("news", "News")
    operations = build_topic_operations(service)
    result = await operations["messaging.topic.subscribe"](
        "订阅news",
        context("", actor, conversation=target),
    )
    assert text_of(result) == "已订阅。"
    assert service.store.subscribers("news") == (target,)


def test_claims_atomic_expiry_and_500_history(tmp_path: Path) -> None:
    store = SqlitePushTopicStore(tmp_path / "state.sqlite")
    assert store.claim("news", GROUP, "same", 10000) is not None
    assert store.claim("news", GROUP, "same", 10001) is None
    assert store.claim("news", OTHER, "same", 10001) is not None
    assert store.claim("news", GROUP, "same", 13601) is not None
    for index in range(505):
        claim = store.claim("news", GROUP, f"unique-{index}", 20000)
        assert claim is not None
        store.finish(claim, "delivered")
    store.prune("news", 20001)
    assert len(store.history("news")) == HISTORY_LIMIT
    assert store.claim("news", GROUP, "unique-0", 20002) is None
    store.prune("news", 24000)
    with store.database.connect() as db:
        assert (
            db.execute("SELECT COUNT(*) FROM push_topic_deliveries").fetchone()[0]
            == HISTORY_LIMIT
        )
