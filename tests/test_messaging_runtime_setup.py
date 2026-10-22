from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.message_schedule_targets import (
    build_message_schedule_targets,
)
from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.features import FeatureConfig, build_feature_service
from ironsbot.config.models.messaging import (
    CommandCooldownConfig,
    CommandCooldownWindowConfig,
    MessageCommandAction,
    MessageConfig,
    MessageKeywordReplyAction,
    MessageMentionReplyAction,
    MessageScheduledAction,
    PushUnsubscribeConfig,
)
from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import MentionPart, OutboundMessage, SendResult, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.storage.push_subscriptions import (
    PushPreferencePruneResult,
    PushUnsubscribeStore,
)
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.identity_link_store import CrossPlatformGroupLink
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging import schedules as message_schedules
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.messaging.command_contracts import messaging_command_contracts
from ironsbot.services.messaging.command_cooldown import CommandCooldownService
from ironsbot.services.messaging.push_time import PushTimeOption
from ironsbot.services.messaging.scheduled_outbound import (
    ScheduledMessageOutboundSender,
)
from ironsbot.services.messaging.service import MessagingService
from ironsbot.services.messaging.subscriptions import (
    ACTIVITY_LEAD_HOURS_PREFERENCE,
    CRON_TIME_PREFERENCE,
    PushSubscriptionOption,
)
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_messaging_commands import (
    build_portable_messaging_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import deliver_portable_reply
from tests.helpers.onebot_events import (
    GroupMemberRole,
    group_member_message_event,
    group_message_event,
    private_message_event,
)
from tests.helpers.onebot_inputs import command_context, message_input_context
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from pytest import MonkeyPatch

    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.ai.service import AiService
    from ironsbot.services.messaging.scheduled_delivery import (
        ScheduledMessageDelivery,
    )
SUPERUSER_ID = 1002
OVERRIDE_HOUR = 22
OVERRIDE_MINUTE = 30


@dataclass(slots=True)
class FakeJob:
    id: str


def _schedule(
    message: str,
    *,
    at_user_ids: Sequence[str | int] | None = None,
    schedule_id: str = "daily",
    time: str = "23:00",
) -> MessageScheduledAction:
    return MessageScheduledAction(
        id=schedule_id,
        messages=[message],
        at_user_ids=list(at_user_ids or []),
        time=time,
    )


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def add_job(self, func: object, trigger: str, **kwargs: object) -> FakeJob:
        job_id = kwargs.get("id")
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]
        self.jobs.append({"func": func, "trigger": trigger, **kwargs})
        return FakeJob(id=str(job_id))

    def get_jobs(self) -> Sequence[FakeJob]:
        return [FakeJob(id=str(job["id"])) for job in self.jobs]

    def remove_job(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job.get("id") != job_id]


def _messaging_resources(  # noqa: PLR0913 - focused test fixture factory
    data_path: Path,
    *,
    commands: list[MessageCommandAction] | None = None,
    keyword_replies: list[MessageKeywordReplyAction] | None = None,
    mention_replies: list[MessageMentionReplyAction] | None = None,
    mention_reply_targets: tuple[tuple[ActorRef, ...], ...] = (),
    schedules: list[MessageScheduledAction] | None = None,
    group_policy: dict[str, list[str]] | None = None,
    user_policy: dict[str, list[str]] | None = None,
    superusers: tuple[int, ...] = (),
    store: PushUnsubscribeStore | None = None,
    extra_push_options: (
        Callable[[ConversationRef], list[PushSubscriptionOption]] | None
    ) = None,
) -> MessagingService:
    config = MessageConfig(
        push_unsubscribe=PushUnsubscribeConfig(),
        commands=commands or [],
        keyword_replies=keyword_replies or [],
        mention_replies=mention_replies or [],
        schedules=schedules or [],
    )
    resources = build_test_runtime(
        feature_config=FeatureConfig(
            group_policy=group_policy or {},
            user_policy=user_policy or {},
        ),
        superuser_ids=superusers,
        state_path=data_path,
    )
    return MessagingService(
        config,
        ActivityConfig(),
        store or PushUnsubscribeStore(data_path),
        resources.features,
        ScheduledMessageOutboundSender(resources.proactive_delivery),
        build_message_schedule_targets(
            config,
            resources.qq_references,
        ),
        (extra_push_options or (lambda _conversation: []),),
        _mention_reply_targets=mention_reply_targets,
    )


def _group_event(
    text: str = "TD",
    *,
    user_id: int = SUPERUSER_ID,
    role: GroupMemberRole = "member",
):
    return group_member_message_event(
        text,
        user_id=user_id,
        group_id=2002,
        role=role,
    )


def _group(group_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "group", str(group_id))


def _private(user_id: int) -> ConversationRef:
    return ConversationRef(Platform.ONEBOT, "private", str(user_id))


def _actor(user_id: int) -> ActorRef:
    return ActorRef(Platform.ONEBOT, str(user_id))


def _capture_scheduled_deliveries(
    monkeypatch: MonkeyPatch,
) -> list[ScheduledMessageDelivery]:
    deliveries: list[ScheduledMessageDelivery] = []

    async def capture(
        _sender: ScheduledMessageOutboundSender,
        delivery: ScheduledMessageDelivery,
    ) -> None:
        deliveries.append(delivery)

    monkeypatch.setattr(ScheduledMessageOutboundSender, "send", capture)
    return deliveries


def test_messaging_startup_prunes_preferences_before_registering_jobs(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_prune(_messaging: MessagingService) -> PushPreferencePruneResult:
        calls.append("prune")
        return PushPreferencePruneResult(
            unsubscriptions_deleted=2,
            time_preferences_deleted=1,
        )

    async def fake_register(
        _messaging: MessagingService,
        _scheduler: object,
    ) -> None:
        calls.append("register")

    monkeypatch.setattr(MessagingService, "_prune_stale_preferences", fake_prune)
    monkeypatch.setattr(MessagingService, "register_schedules", fake_register)

    asyncio.run(
        _messaging_resources(tmp_path / "unsubscribe.sqlite").start(
            FakeScheduler(),
        )
    )

    assert calls == ["prune", "register"]


def test_messaging_startup_continues_when_preference_cleanup_fails(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def fake_prune(_messaging: MessagingService) -> PushPreferencePruneResult:
        calls.append("prune")
        raise RuntimeError

    async def fake_register(
        _messaging: MessagingService,
        _scheduler: object,
    ) -> None:
        calls.append("register")

    monkeypatch.setattr(MessagingService, "_prune_stale_preferences", fake_prune)
    monkeypatch.setattr(MessagingService, "register_schedules", fake_register)

    asyncio.run(
        _messaging_resources(tmp_path / "unsubscribe.sqlite").start(
            FakeScheduler(),
        )
    )

    assert calls == ["prune", "register"]


def test_push_time_refresh_uses_explicit_job_owner(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, object]] = []

    async def fake_register(
        _messaging: MessagingService,
        scheduler: object,
    ) -> None:
        calls.append(("message", scheduler))

    class FakeActivityService:
        async def schedule_reminders(self, scheduler: object) -> None:
            calls.append(("activity", scheduler))

    scheduler = FakeScheduler()
    activity_service = cast("ActivityService", FakeActivityService())
    messaging = _messaging_resources(tmp_path / "unsubscribe.sqlite")
    monkeypatch.setattr(MessagingService, "register_schedules", fake_register)
    option = PushTimeOption("test", "测试", "test", CRON_TIME_PREFERENCE, "", "")
    for preference_type in (
        CRON_TIME_PREFERENCE,
        ACTIVITY_LEAD_HOURS_PREFERENCE,
    ):
        asyncio.run(
            messaging.refresh_push_time_jobs(
                replace(option, preference_type=preference_type),
                scheduler=scheduler,
                activity_service=activity_service,
            )
        )

    assert calls == [("message", scheduler), ("activity", scheduler)]


def test_push_subscription_menu_prompt_marks_current_state(tmp_path: Path) -> None:
    options = [
        PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
        PushSubscriptionOption(
            "startup_data_sync",
            "启动数据同步通知",
            "admin_notice",
            unsubscribed=True,
        ),
    ]
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        extra_push_options=lambda _conversation: options,
    )
    _, prompt = messaging.subscription_menu(
        ConversationRef(Platform.ONEBOT, "private", "1001"),
    )

    assert "请选择要切换的私聊推送订阅：" in prompt
    assert "1. ✅ 机器人启动通知" in prompt
    assert "2. ❌ 启动数据同步通知" in prompt
    assert "输入序号切换" in prompt


def test_td_displays_effective_schedule_and_activity_times(tmp_path: Path) -> None:
    conversation = _private(1001)
    store = PushUnsubscribeStore(tmp_path / "unsubscribe.sqlite")
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        schedules=[
            MessageScheduledAction(
                id="web_daily",
                name="网页活动提醒",
                feature="web_activity_push",
                messages=["提醒"],
                time="19:00",
            )
        ],
        user_policy={
            "1001": ["web_activity_push", "seer_activity_push", "admin_notice"]
        },
        store=store,
    )
    messaging = replace(messaging, _activity=ActivityConfig(lead_hours=[11, 1]))

    def labels() -> dict[str, str]:
        return {
            option.key: option.label
            for option in messaging.subscription_options(conversation)
        }

    assert labels()["web_daily"] == "网页活动提醒（每日 19:00:00）"
    assert labels()["seer_activity_push"] == "活动结束提醒（截止前 11、1 小时）"
    assert labels()["startup_notice"] == "机器人启动通知"

    time_options = {
        option.key: option for option in messaging.push_time_options(conversation)
    }
    messaging.update_push_time(
        conversation=conversation, option=time_options["web_daily"], value="20:15:30"
    )
    messaging.update_push_time(
        conversation=conversation,
        option=time_options["seer_activity_push"],
        value="24,3",
    )
    assert labels()["web_daily"] == "网页活动提醒（每日 20:15:30）"
    assert labels()["seer_activity_push"] == "活动结束提醒（截止前 24、3 小时）"

    messaging.update_push_time(
        conversation=conversation, option=time_options["web_daily"], value=None
    )
    messaging.update_push_time(
        conversation=conversation,
        option=time_options["seer_activity_push"],
        value=None,
    )
    assert labels()["web_daily"] == "网页活动提醒（每日 19:00:00）"
    assert labels()["seer_activity_push"] == "活动结束提醒（截止前 11、1 小时）"


def test_push_subscription_menu_prompt_can_be_read_only(tmp_path: Path) -> None:
    options = [
        PushSubscriptionOption("startup_notice", "机器人启动通知", "admin_notice"),
    ]
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        extra_push_options=lambda _conversation: options,
    )
    _, prompt = messaging.subscription_menu(
        ConversationRef(Platform.ONEBOT, "group", "1001"),
        read_only=True,
    )

    assert "推送订阅状态：" in prompt
    assert "1. ✅ 机器人启动通知" in prompt
    assert "普通群员仅可查看" in prompt
    assert "输入序号切换" not in prompt


def test_push_subscription_menu_keeps_read_only_options_when_names_fail(
    tmp_path: Path,
) -> None:
    warning = "⚠️ 暂时无法刷新公开昵称，使用 UID 显示。"

    async def prepare(_conversation: ConversationRef) -> str:
        return warning

    options = [
        PushSubscriptionOption("bili_push:123", "B站动态（UID：123）", "bili_push"),
    ]
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        extra_push_options=lambda _conversation: options,
    )
    messaging = replace(messaging, _prepare_extra_push_options=prepare)

    resolved_options, prompt = asyncio.run(
        messaging.prepared_subscription_menu(
            ConversationRef(Platform.ONEBOT, "group", "1001"),
            read_only=True,
        )
    )

    assert resolved_options == options
    assert prompt.startswith(warning)
    assert "1. ✅ B站动态（UID：123）" in prompt
    assert "普通群员仅可查看" in prompt


def test_group_push_subscription_command_allows_superuser_member(
    tmp_path: Path,
) -> None:
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite", superusers=(SUPERUSER_ID,)
    )
    assert _messaging_router(MessageConfig(), messaging).recognizes(
        message_input_context(_group_event())
    )


def test_group_push_subscription_command_allows_regular_member_to_view(
    tmp_path: Path,
) -> None:
    messaging = _messaging_resources(tmp_path / "unsubscribe.sqlite")
    assert _messaging_router(MessageConfig(), messaging).recognizes(
        message_input_context(_group_event())
    )


def test_group_push_subscription_management_command_matches_regular_member(
    tmp_path: Path,
) -> None:
    messaging = _messaging_resources(tmp_path / "unsubscribe.sqlite")
    assert _messaging_router(MessageConfig(), messaging).recognizes(
        message_input_context(_group_event("推送管理", user_id=3003))
    )


def _messaging_catalog(config: MessageConfig) -> CommandCatalog:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(
                id="messaging", commands=messaging_command_contracts(config)
            ),
        ),
        known_features={"text", "ai_chat"},
    )
    return catalog


def _messaging_router(
    config: MessageConfig,
    messaging: MessagingService,
    sessions: PortableQuerySessions | None = None,
) -> PortableCommandRouter:
    catalog = _messaging_catalog(config)
    sessions = sessions or PortableQuerySessions()

    async def refresh(_option: PushTimeOption) -> None:
        pass

    return PortableCommandRouter(
        catalog,
        build_portable_messaging_operations(
            messaging, sessions, refresh_push_time_jobs=refresh
        ),
        messaging.feature_policy,
        ai=cast("AiService", None),
        ai_input_routing=AiInputRoutingService(messaging.feature_policy, catalog),
        addressed_input_hints=AddressedInputHintService(),
        messaging=messaging,
        query_sessions=sessions,
    )


@pytest.mark.parametrize(
    "text", ["TD", "td", "退订", "订阅", "恢复订阅", "推送管理", "推送时间", "提醒时间"]
)
def test_push_menu_private_entry_is_claimed_and_not_captured_by_ai(
    tmp_path: Path, text: str
) -> None:
    messaging = _messaging_resources(
        tmp_path / "qq.sqlite", user_policy={"1002": ["ai_chat"]}
    )
    catalog = _messaging_catalog(MessageConfig())
    event = private_message_event(text, user_id=SUPERUSER_ID)
    assert _messaging_router(MessageConfig(), messaging).recognizes(
        message_input_context(event)
    )
    assert catalog.claims_direct_input(
        CommandContext(_actor(SUPERUSER_ID), _private(SUPERUSER_ID)),
        messaging.feature_policy,
        text,
    )
    assert (
        not AiInputRoutingService(messaging.feature_policy, catalog)
        .decide(message_input_context(event), command_context(event))
        .try_chat
    )


@pytest.mark.parametrize("text", ["TD", "推送时间"])
@pytest.mark.parametrize("role", ["member", "admin", "owner"])
@pytest.mark.parametrize("superuser", [False, True])
def test_push_menu_group_directory_agrees_with_actual_permission(
    tmp_path: Path, text: str, role: GroupMemberRole, *, superuser: bool
) -> None:
    messaging = _messaging_resources(
        tmp_path / "qq.sqlite", superusers=(SUPERUSER_ID,) if superuser else ()
    )
    event = _group_event(text, role=role)
    expected = text == "TD" or superuser or role != "member"
    assert (
        _messaging_router(MessageConfig(), messaging).recognizes(
            message_input_context(event)
        )
        is expected
    )
    assert (
        _messaging_catalog(MessageConfig()).claims_direct_input(
            CommandContext(_actor(SUPERUSER_ID), _group(2002), role),
            messaging.feature_policy,
            text,
        )
        is expected
    )


def test_push_menu_custom_commands_and_non_entry_inputs(tmp_path: Path) -> None:
    config = MessageConfig(
        push_unsubscribe=PushUnsubscribeConfig(
            commands=["stop", "暂停推送"], restore_commands=["resume", "恢复推送"]
        )
    )
    messaging = replace(_messaging_resources(tmp_path / "qq.sqlite"), _config=config)
    catalog = _messaging_catalog(config)
    context = CommandContext(_actor(SUPERUSER_ID), _private(SUPERUSER_ID))
    for text in ("STOP", "暂停推送", "resume", "恢复推送", "推送管理"):
        assert messaging.matches_subscription_command(text)
        assert catalog.claims_direct_input(context, messaging.feature_policy, text)
    for text in ("TD", "订阅", "0", "1", "23:00", "/推送管理", "聊一下推送"):
        assert not messaging.matches_subscription_command(text)
        assert not catalog.claims_direct_input(context, messaging.feature_policy, text)


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("keyword", [False, True])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.asyncio
async def test_shared_router_prefers_enabled_exact_reply_over_keyword(
    tmp_path: Path, *, configured: bool, keyword: bool, enabled: bool
) -> None:
    config = MessageConfig(
        commands=[
            MessageCommandAction(
                id="example", commands=["示例"], messages=["exact"], enabled=enabled
            )
        ]
        if configured
        else [],
        keyword_replies=[
            MessageKeywordReplyAction(
                id="example", keywords=["示例"], messages=["keyword"], enabled=enabled
            )
        ]
        if keyword
        else [],
    )
    messaging = replace(
        _messaging_resources(tmp_path / "qq.sqlite", user_policy={"1002": ["text"]}),
        _config=config,
    )
    router = _messaging_router(config, messaging)
    for text in ("示例", "包含示例的文字", "无关"):
        event = private_message_event(text, user_id=SUPERUSER_ID)
        reply = await router.dispatch(message_input_context(event))
        expected = (
            "exact"
            if enabled and configured and text == "示例"
            else "keyword"
            if enabled and keyword and text == "示例"
            else None
        )
        assert (reply.message if reply is not None else None) == (
            OutboundMessage.from_text(expected) if expected is not None else None
        )


@pytest.mark.asyncio
async def test_shared_router_executes_configured_mention_reply(
    tmp_path: Path,
) -> None:
    action = MessageMentionReplyAction(
        id="example",
        users=["example"],
        messages=["reply"],
    )
    config = MessageConfig(mention_replies=[action])
    messaging = replace(
        _messaging_resources(tmp_path / "qq.sqlite"),
        _config=config,
        _mention_reply_targets=((_actor(2002),),),
    )
    router = _messaging_router(config, messaging)
    event = group_message_event(
        user_id=2002,
        group_id=1001,
        self_id=1,
        message=Message([MessageSegment.at(1)]),
    )
    context = message_input_context(event)
    assert router.recognizes(context)
    reply = await router.dispatch(context)
    assert reply is not None
    assert reply.message == OutboundMessage.from_text("reply")


def test_mention_reply_respects_conversation_blacklist(tmp_path: Path) -> None:
    configured = _actor(2002)
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        mention_replies=[
            MessageMentionReplyAction(
                id="example",
                users=["example"],
                messages=["reply"],
            )
        ],
        mention_reply_targets=((configured,),),
        group_policy={"1001": ["blacklist"]},
    )

    assert (
        messaging.match_mention_reply(_mention_context(configured, _group(1001)))
        is None
    )


@pytest.mark.parametrize("exact_enabled", [True, False])
@pytest.mark.parametrize("exact_allowed", [True, False])
@pytest.mark.parametrize("keyword_allowed", [True, False])
def test_reply_selection_checks_each_action_permission_before_precedence(
    tmp_path: Path, *, exact_enabled: bool, exact_allowed: bool, keyword_allowed: bool
) -> None:
    messaging = _messaging_resources(
        tmp_path / "qq.sqlite",
        commands=[
            MessageCommandAction(
                id="same",
                commands=["示例"],
                messages=["exact"],
                feature="seerinfo",
                enabled=exact_enabled,
            )
        ],
        keyword_replies=[
            MessageKeywordReplyAction(
                id="same",
                keywords=["示例"],
                messages=["keyword"],
                feature="web_activity_link",
            )
        ],
        user_policy={
            "1002": [
                *(["seerinfo"] if exact_allowed else []),
                *(["web_activity_link"] if keyword_allowed else []),
            ]
        },
    )
    direct = messaging.match_action(
        "示例",
        actor=_actor(SUPERUSER_ID),
        conversation=_private(SUPERUSER_ID),
        interaction="direct",
    )
    automatic = messaging.match_action(
        "示例",
        actor=_actor(SUPERUSER_ID),
        conversation=_private(SUPERUSER_ID),
        interaction="automatic",
    )
    assert (direct is not None) is (exact_enabled and exact_allowed)
    assert (automatic is not None) is (
        keyword_allowed and not (exact_enabled and exact_allowed)
    )


def test_automatic_reply_does_not_become_a_direct_command_or_poke_hint() -> None:
    config = MessageConfig(
        keyword_replies=[
            MessageKeywordReplyAction(
                id="example", keywords=["示例"], messages=["keyword"]
            )
        ]
    )
    catalog = _messaging_catalog(config)
    runtime = build_test_runtime(
        feature_config=FeatureConfig(user_policy={"1002": ["text"]})
    )
    context = CommandContext(_actor(SUPERUSER_ID), _private(SUPERUSER_ID))
    assert not catalog.claims_direct_input(context, runtime.features, "示例")
    assert "messaging.keyword.example" not in {
        c.id for c in catalog.poke_candidates_for_context(context, runtime.features)
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
async def test_reply_cooldown_keys_distinguish_same_named_action_families(
    tmp_path: Path,
    platform: Platform,
) -> None:
    config = MessageConfig(
        commands=[
            MessageCommandAction(id="same", commands=["指令"], messages=["direct"])
        ],
        keyword_replies=[
            MessageKeywordReplyAction(
                id="same", keywords=["触发"], messages=["keyword"]
            )
        ],
    )
    messaging = _messaging_resources(
        tmp_path / "qq.sqlite",
        commands=config.commands,
        keyword_replies=config.keyword_replies,
        user_policy={"2001": ["text"]},
        superusers=(),
    )
    actor = ActorRef(platform, "2001")
    conversation = ConversationRef(platform, "private", actor.id)
    messaging = replace(
        messaging,
        _features=FeatureService({}, {actor: frozenset({"text"})}, frozenset()),
    )
    sessions = PortableQuerySessions()
    cooldown = Mock(
        wraps=CommandCooldownService(
            CommandCooldownConfig(
                enabled=True,
                windows=[
                    CommandCooldownWindowConfig(window_seconds=60, max_requests=1)
                ],
            ),
            messaging.feature_policy,
        )
    )
    sessions.interactions.cooldown = cooldown
    router = _messaging_router(config, messaging, sessions)
    messages = []
    for text in ("指令", "触发", "触发"):
        reply = await router.dispatch(
            MessageInputContext(
                IncomingMessageRef(
                    platform, actor, conversation, str(len(messages)), text
                ),
                mentions_bot=False,
            )
        )
        assert reply is not None
        messages.append(
            "".join(
                part.text for part in reply.message.parts if isinstance(part, TextPart)
            )
        )
        await deliver_portable_reply(
            reply,
            AsyncMock(
                return_value=SendResult(delivered=True, message_id=str(len(messages)))
            ),
        )
    assert messages[:2] == ["direct", "keyword"]
    assert "操作过于频繁" in messages[-1]
    assert [call.kwargs["command_id"] for call in cooldown.admit.call_args_list] == [
        "messaging.same",
        "messaging.keyword.same",
        "messaging.keyword.same",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("group", [False, True])
async def test_keyword_reply_preserves_active_subscription_menu(
    tmp_path: Path, platform: Platform, *, group: bool
) -> None:
    config = MessageConfig(
        keyword_replies=[
            MessageKeywordReplyAction(
                id="example", keywords=["触发"], messages=["keyword"]
            )
        ]
    )
    actor = ActorRef(platform, "2001")
    conversation = ConversationRef(platform, "group" if group else "private", "2001")
    store = PushUnsubscribeStore(tmp_path / "qq.sqlite")
    messaging = replace(
        _messaging_resources(
            tmp_path / "qq.sqlite",
            keyword_replies=config.keyword_replies,
            store=store,
            extra_push_options=lambda _conversation: [
                PushSubscriptionOption("example", "示例", "text")
            ],
        ),
        _features=FeatureService(
            {conversation: frozenset({"text"})} if group else {},
            {actor: frozenset({"text"})},
            frozenset(),
        ),
    )
    sessions = PortableQuerySessions()
    router = _messaging_router(config, messaging, sessions)

    async def dispatch(text: str):
        context = MessageInputContext(
            IncomingMessageRef(
                platform,
                actor,
                conversation,
                text,
                text,
                group_role="admin" if group else None,
            ),
            mentions_bot=False,
        )
        reply = await router.dispatch(context)
        assert reply is not None
        await deliver_portable_reply(
            reply, AsyncMock(return_value=SendResult(delivered=True, message_id=text))
        )
        return context, reply

    context, _ = await dispatch("TD")
    prompt = sessions.active_prompt(context)
    assert prompt is not None
    _, reply = await dispatch("触发")
    assert reply.message == OutboundMessage.from_text("keyword")
    assert sessions.active_prompt(context) == prompt
    await dispatch("1")
    assert store.is_unsubscribed(conversation, "example")


@pytest.mark.asyncio
async def test_onebot_configured_reply_sends_messages_in_order(
    tmp_path: Path,
) -> None:
    sent: list[str] = []

    async def record(message: OutboundMessage) -> SendResult:
        sent.append("".join(p.text for p in message.parts if isinstance(p, TextPart)))
        return SendResult(delivered=True, message_id=str(len(sent)))

    action = MessageCommandAction(
        id="sequence",
        commands=["连续回复"],
        messages=["第一条", "第二条", "第三条"],
    )
    messaging = _messaging_resources(
        tmp_path / "qq.sqlite",
        commands=[action],
        user_policy={str(SUPERUSER_ID): ["text"]},
    )
    reply = await _messaging_router(
        MessageConfig(commands=[action]), messaging
    ).dispatch(
        message_input_context(private_message_event("连续回复", user_id=SUPERUSER_ID))
    )
    assert reply is not None
    await deliver_portable_reply(reply, record)
    assert sent == action.messages


@pytest.mark.asyncio
async def test_onebot_configured_reply_addresses_explicit_member_targets(
    tmp_path: Path,
) -> None:
    sent_targets: list[tuple[int, ...]] = []

    async def record(
        message: OutboundMessage,
    ) -> SendResult:
        sent_targets.append(
            tuple(int(p.actor.id) for p in message.parts if isinstance(p, MentionPart))
        )
        return SendResult(delivered=True, message_id="targeted")

    action = MessageCommandAction(
        id="targeted",
        commands=["加群"],
        messages=["加群信息"],
        at_user_ids=[790],
    )
    event = group_message_event(
        message=Message("加群 ") + MessageSegment.at(789) + MessageSegment.at(789),
    )

    messaging = replace(
        _messaging_resources(
            tmp_path / "qq.sqlite",
            commands=[action],
            group_policy={str(event.group_id): ["text"]},
        ),
        _command_mentions={"targeted": (_actor(790),)},
    )
    reply = await _messaging_router(
        MessageConfig(commands=[action]), messaging
    ).dispatch(message_input_context(event))
    assert reply is not None
    await deliver_portable_reply(reply, record)

    assert sent_targets == [(789,)]


def test_unified_command_action_uses_feature_policy_for_each_message_scope(
    tmp_path: Path,
) -> None:
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        commands=[
            MessageCommandAction(
                id="activity_link",
                commands=["activity"],
                feature="web_activity_link",
                messages=["activity link"],
                at_user_ids=[3001],
            )
        ],
        user_policy={"2001": ["web_activity_link"]},
        group_policy={"1001": ["web_activity_link"]},
    )

    private_action = messaging.match_action(
        "activity",
        actor=_actor(2001),
        conversation=_private(2001),
        interaction="direct",
    )
    group_action = messaging.match_action(
        "activity",
        actor=_actor(2002),
        conversation=_group(1001),
        interaction="direct",
    )
    assert private_action is not None
    assert group_action is not None
    assert private_action.id == "activity_link"
    assert group_action.at_user_ids == [3001]


def test_keyword_reply_uses_feature_policy_after_exact_commands(
    tmp_path: Path,
) -> None:
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        commands=[
            MessageCommandAction(
                id="exact_reply",
                commands=["出出"],
                feature="text",
                messages=["精确回复"],
            )
        ],
        keyword_replies=[
            MessageKeywordReplyAction(
                id="keyword_reply",
                keywords=["出出", "自动词"],
                feature="text",
                messages=["关键词回复"],
            )
        ],
        group_policy={"1001": ["text"]},
    )

    exact_action = messaging.match_action(
        "出出",
        actor=_actor(2002),
        conversation=_group(1001),
        interaction="direct",
    )
    keyword_action = messaging.match_action(
        "自 动词",
        actor=_actor(2002),
        conversation=_group(1001),
        interaction="automatic",
    )
    assert exact_action is not None
    assert keyword_action is not None
    assert exact_action.id == "exact_reply"
    assert keyword_action.id == "keyword_reply"
    assert (
        messaging.match_action(
            "今天出出了",
            actor=_actor(2002),
            conversation=_group(1001),
            interaction="automatic",
        )
        is None
    )


@pytest.mark.parametrize("allowed", [True, False])
def test_onebot_contains_reply_permissions_and_fixed_command_priority(
    tmp_path: Path,
    *,
    allowed: bool,
) -> None:
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        commands=[
            MessageCommandAction(
                id="fixed",
                commands=["竞技胜率榜"],
                feature="seerinfo",
                messages=["fixed"],
            )
        ],
        keyword_replies=[
            MessageKeywordReplyAction(
                id="webpage",
                keywords=["竞技胜率榜", "竞技精灵胜率榜"],
                match_mode="contains",
                feature="seerinfo",
                messages=["https://example.com/sports"],
            ),
            MessageKeywordReplyAction(
                id="second",
                keywords=["胜率榜"],
                match_mode="contains",
                feature="seerinfo",
                messages=["second"],
            ),
        ],
        group_policy={"1001": ["seerinfo"] if allowed else []},
    )
    action = messaging.match_action(
        "看看竞技胜率榜",
        actor=_actor(2002),
        conversation=_group(1001),
        interaction="automatic",
    )
    assert (action is not None) is allowed
    if allowed:
        assert action is not None
        assert action.id == "webpage"
    assert (
        messaging.match_action(
            "竞技胜率榜",
            actor=_actor(2002),
            conversation=_group(1001),
            interaction="automatic",
        )
        is None
    )
    assert (
        messaging.match_action(
            "竞技胜率榜",
            actor=_actor(2002),
            conversation=_group(1001),
            interaction="direct",
        )
        is not None
    ) is allowed


def _mention_context(
    actor: ActorRef,
    conversation: ConversationRef,
    *,
    mentions_bot: bool = True,
) -> MessageInputContext:
    return MessageInputContext(
        IncomingMessageRef(
            actor.platform,
            actor,
            conversation,
            "message-1",
            "",
        ),
        mentions_bot=mentions_bot,
    )


def test_mention_reply_requires_the_configured_actor_and_bot_mention(
    tmp_path: Path,
) -> None:
    configured = _actor(2002)
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        mention_replies=[
            MessageMentionReplyAction(
                id="example",
                users=["example"],
                messages=["first", "second"],
            )
        ],
        mention_reply_targets=((configured,),),
    )
    conversation = _group(1001)

    action = messaging.match_mention_reply(_mention_context(configured, conversation))

    assert action is not None
    assert action.messages == ["first", "second"]
    assert (
        messaging.match_mention_reply(_mention_context(_actor(2003), conversation))
        is None
    )
    assert (
        messaging.match_mention_reply(
            _mention_context(configured, conversation, mentions_bot=False)
        )
        is None
    )


def test_onebot_context_uses_shared_mention_reply_matching(
    tmp_path: Path,
) -> None:
    configured = _actor(2002)
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        mention_replies=[
            MessageMentionReplyAction(
                id="example",
                users=["example"],
                messages=["reply"],
            )
        ],
        mention_reply_targets=((configured,),),
    )
    event = group_message_event(
        user_id=2002,
        group_id=1001,
        self_id=1,
        message=Message([MessageSegment.at(1)]),
    )

    action = messaging.match_mention_reply(message_input_context(event))
    assert action is not None
    assert action.id == "example"


def test_mention_reply_matches_the_same_principal_across_official_accounts(
    tmp_path: Path,
) -> None:
    principals = IdentityPrincipalService()
    principals.register_configured_actor(
        alias="example",
        onebot_qq_id="2002",
        official_endpoints=(("app-a", "member-a"), ("app-b", "member-b")),
    )
    target = _actor(2002)
    messaging = replace(
        _messaging_resources(
            tmp_path / "unsubscribe.sqlite",
            mention_replies=[
                MessageMentionReplyAction(
                    id="example",
                    users=["example"],
                    messages=["shared reply"],
                )
            ],
            mention_reply_targets=((target,),),
        ),
        _actor_principal=principals.actor_principal,
    )
    official_actor = ActorRef(
        Platform.QQ_OFFICIAL,
        "member-b",
        "member",
        "group-b",
        account_id="app-b",
    )
    official_group = ConversationRef(
        Platform.QQ_OFFICIAL,
        "group",
        "group-b",
        account_id="app-b",
    )

    action = messaging.match_mention_reply(
        _mention_context(official_actor, official_group)
    )

    assert action is not None
    assert action.id == "example"


def test_unified_schedule_delivers_to_private_and_group_targets(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _capture_scheduled_deliveries(monkeypatch)
    task = _schedule("shared schedule", at_user_ids=[3001])
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        user_policy={"2001": ["text_push"]},
        group_policy={"1001": ["text_push"]},
        schedules=[task],
    )

    asyncio.run(
        message_schedules.send_schedule(
            task,
            messaging=messaging,
        )
    )

    assert sent[0].private_conversations == (_private(2001),)
    assert sent[0].subscription_key == "daily"
    assert sent[1].group_conversations == (_group(1001),)
    assert sent[1].group_mentions == (_actor(3001),)
    assert sent[1].subscription_key == "daily"


def test_private_renderer_limits_countdown_to_configured_group(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _capture_scheduled_deliveries(monkeypatch)
    task = MessageScheduledAction(
        id="exam_countdown",
        feature="text_push",
        messages=["{days} days"],
        time="12:00",
        renderer="private.exam_countdown",
        target_groups=[1001],
        at_user_ids=[3001],
        unresolved_mentions="text",
        mention_fallback_name="student",
    )
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        user_policy={"2001": ["text_push"]},
        group_policy={"1001": ["text_push"], "1002": ["text_push"]},
        schedules=[task],
    )
    messaging.schedule_renderers.register(
        task.renderer,
        lambda _request: ("3 days",),
    )

    asyncio.run(message_schedules.send_schedule(task, messaging=messaging))

    assert len(sent) == 1
    assert sent[0].group_conversations == (_group(1001),)
    assert sent[0].private_conversations == ()
    assert sent[0].messages == ("3 days",)
    assert sent[0].unresolved_mentions_as_text
    assert sent[0].mention_fallback_name == "student"


def test_targeted_schedule_only_appears_in_target_group_subscription_menu(
    tmp_path: Path,
) -> None:
    task = MessageScheduledAction(
        id="exam_countdown",
        name="Exam countdown",
        feature="text_push",
        messages=["{days} days"],
        time="12:00",
        renderer="private.exam_countdown",
        target_groups=[1001],
    )
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        user_policy={"2001": ["text_push"]},
        group_policy={"1001": ["text_push"], "1002": ["text_push"]},
        schedules=[task],
    )

    assert [option.key for option in messaging.subscription_options(_group(1001))] == [
        task.id
    ]
    assert messaging.subscription_options(_group(1002)) == []
    assert messaging.subscription_options(_private(2001)) == []


def test_target_group_follows_verified_official_group_link(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _capture_scheduled_deliveries(monkeypatch)
    task = MessageScheduledAction(
        id="exam_countdown",
        feature="text_push",
        messages=["Reminder"],
        time="12:00",
        target_groups=[1001],
    )
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        group_policy={"1001": ["text_push"], "1002": ["text_push"]},
        schedules=[task],
    )
    principals = IdentityPrincipalService()
    messaging = replace(
        messaging,
        _features=build_feature_service(
            FeatureConfig(group_policy={"1001": ["text_push"], "1002": ["text_push"]}),
            (),
            principals=principals,
        ),
    )
    official = ConversationRef(
        Platform.QQ_OFFICIAL, "group", "example-group", account_id="example-app"
    )
    principals.register_group_link(
        CrossPlatformGroupLink("1001", "example-app", "example-group", 1.0)
    )

    asyncio.run(message_schedules.send_group_schedule(task, messaging=messaging))

    assert set(sent[0].group_conversations) == {_group(1001), official}
    assert [option.key for option in messaging.subscription_options(official)] == [
        task.id
    ]
    assert messaging.subscription_options(official)[0].label.endswith(
        "（每日 12:00:00）"
    )


def test_missing_private_renderer_never_sends_template(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sent = _capture_scheduled_deliveries(monkeypatch)
    task = MessageScheduledAction(
        id="exam_countdown",
        feature="text_push",
        messages=["{days} days"],
        time="12:00",
        renderer="private.exam_countdown",
    )
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        group_policy={"1001": ["text_push"]},
        schedules=[task],
    )

    asyncio.run(message_schedules.send_schedule(task, messaging=messaging))

    assert sent == []
    assert "scheduled message renderer unavailable" in caplog.text


def test_scheduled_messages_build_typed_private_and_group_deliveries(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _capture_scheduled_deliveries(monkeypatch)
    private_task = _schedule("私聊定时", schedule_id="private")
    group_task = _schedule("群定时", at_user_ids=[3001], schedule_id="group")
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        user_policy={"2001": ["text_push"]},
        group_policy={"1001": ["text_push", "fire_manual_ad"]},
        schedules=[group_task],
    )

    asyncio.run(
        message_schedules.send_private_schedule(
            private_task,
            messaging=messaging,
        )
    )
    asyncio.run(
        message_schedules.send_group_schedule(
            group_task,
            messaging=messaging,
        )
    )

    assert [delivery.messages for delivery in sent] == [
        ("私聊定时",),
        ("群定时",),
    ]
    assert sent[0].private_conversations == (_private(2001),)
    assert sent[0].subscription_key == "private"
    assert sent[1].group_conversations == (_group(1001),)
    assert sent[1].group_mentions == (_actor(3001),)
    assert sent[1].subscription_key == "group"


def test_private_schedule_builds_typed_delivery_for_enabled_user(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _capture_scheduled_deliveries(monkeypatch)
    messaging = _messaging_resources(
        tmp_path / "unsubscribe.sqlite",
        user_policy={"2001": ["text_push", "fire_manual_ad"]},
    )

    asyncio.run(
        message_schedules.send_private_schedule(
            _schedule("私聊定时", schedule_id="private"),
            messaging=messaging,
        )
    )

    assert sent[0].messages == ("私聊定时",)
    assert sent[0].private_conversations == (_private(2001),)


def test_private_schedule_passes_subscription_key(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _capture_scheduled_deliveries(monkeypatch)
    data_path = tmp_path / "unsubscribe.sqlite"
    messaging = _messaging_resources(
        data_path,
        user_policy={
            "2001": ["text_push"],
            "2002": ["text_push"],
        },
    )

    asyncio.run(
        message_schedules.send_private_schedule(
            _schedule("私聊定时", schedule_id="private"),
            messaging=messaging,
        )
    )

    assert sent[0].private_conversations == (_private(2001), _private(2002))
    assert sent[0].subscription_key == "private"


def test_group_schedule_skips_default_time_for_overridden_group(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    sent = _capture_scheduled_deliveries(monkeypatch)
    data_path = tmp_path / "unsubscribe.sqlite"
    store = PushUnsubscribeStore(data_path)
    messaging = _messaging_resources(
        data_path,
        group_policy={
            "1001": ["text_push"],
            "1002": ["text_push"],
        },
        store=store,
    )
    store.set_time_preference(
        ConversationRef(Platform.ONEBOT, "group", "1001"),
        "daily",
        CRON_TIME_PREFERENCE,
        f"{OVERRIDE_HOUR:02d}:{OVERRIDE_MINUTE:02d}",
    )

    asyncio.run(
        message_schedules.send_group_schedule(
            _schedule("group push", at_user_ids=[], schedule_id="daily"),
            messaging=messaging,
        )
    )

    assert sent[0].group_conversations == (_group(1002),)
    assert sent[0].subscription_key == "daily"


def test_group_schedule_override_job_targets_only_overridden_group(
    tmp_path: Path,
) -> None:
    data_path = tmp_path / "unsubscribe.sqlite"
    store = PushUnsubscribeStore(data_path)
    store.set_time_preference(
        ConversationRef(Platform.ONEBOT, "group", "1001"),
        "daily",
        CRON_TIME_PREFERENCE,
        f"{OVERRIDE_HOUR:02d}:{OVERRIDE_MINUTE:02d}",
    )
    task = MessageScheduledAction(
        messages=["group push"],
        at_user_ids=[],
        id="daily",
        time="23:00",
    )
    scheduler = FakeScheduler()

    asyncio.run(
        message_schedules.register_message_schedules(
            scheduler,
            _messaging_resources(
                data_path,
                schedules=[task],
                group_policy={
                    "1001": ["text_push"],
                    "1002": ["text_push"],
                },
            ),
        )
    )

    assert [job["id"] for job in scheduler.jobs] == [
        "message_action_schedule_daily",
        "message_action_group_schedule_daily_override_onebot_group_1001",
    ]
    override_job = scheduler.jobs[1]
    assert override_job["hour"] == OVERRIDE_HOUR
    assert override_job["minute"] == OVERRIDE_MINUTE
    assert override_job["kwargs"] == {
        "task": task,
        "index": 1,
        "target_conversations": (ConversationRef(Platform.ONEBOT, "group", "1001"),),
    }
