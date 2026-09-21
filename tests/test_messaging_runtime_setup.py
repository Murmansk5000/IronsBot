from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import nonebot
import pytest
from nonebot.adapters.onebot.v11 import Message, MessageSegment

ROOT = Path(__file__).resolve().parents[1]
os.environ["APP_CONFIG_PATH"] = str(ROOT / "config.example.toml")

try:
    nonebot.get_driver()
except ValueError:
    nonebot.init()

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.features import FeatureConfig
from ironsbot.config.models.messaging import (
    MessageCommandAction,
    MessageConfig,
    MessageKeywordReplyAction,
    MessageMentionReplyAction,
    MessageScheduledAction,
    PushUnsubscribeConfig,
)
from ironsbot.config.onebot_references import OneBotReferenceResolver
from ironsbot.core.command_catalog import CommandCatalog, CommandContext
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.integrations.onebot.conversations import event_conversation_session_id
from ironsbot.integrations.onebot.matcher_support import EXPLICIT_COMMAND_STATE_KEY
from ironsbot.integrations.onebot.messaging_config import (
    build_onebot_message_schedule_targets,
)
from ironsbot.integrations.storage.push_subscriptions import (
    PushPreferencePruneResult,
    PushUnsubscribeStore,
)
from ironsbot.plugins.onebot.ai import _capture_ai_prompt
from ironsbot.plugins.onebot.messaging import matcher_rules, plugin_contribution
from ironsbot.plugins.onebot.messaging import matchers as messaging_matchers
from ironsbot.plugins.onebot.messaging.matchers import _action_command_id
from ironsbot.plugins.onebot.messaging.push_management_runtime import (
    PUSH_SUBSCRIPTION_FLOW,
    PUSH_TIME_FLOW,
    PromptFlow,
)
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.identity_principals import IdentityPrincipalService
from ironsbot.services.messaging import schedules as message_schedules
from ironsbot.services.messaging.command_contracts import messaging_command_contracts
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
from tests.helpers.onebot_events import (
    GroupMemberRole,
    group_member_message_event,
    group_message_event,
    private_message_event,
)
from tests.helpers.runtime import build_test_runtime

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from nonebot.adapters.onebot.v11 import Bot
    from nonebot.matcher import Matcher
    from pytest import MonkeyPatch

    from ironsbot.config.models.messaging import MessageReplyAction
    from ironsbot.services.activity.service import ActivityService
    from ironsbot.services.messaging.scheduled_delivery import (
        ScheduledMessageDelivery,
    )
    from ironsbot.services.operations.scheduler import Scheduler
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
        build_onebot_message_schedule_targets(
            config,
            resources.onebot_references,
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
    assert matcher_rules.match_push_subscription_command(
        _group_event(),
        {},
        messaging=_messaging_resources(tmp_path / "unsubscribe.sqlite"),
    )


def test_group_push_subscription_command_allows_regular_member_to_view(
    tmp_path: Path,
) -> None:
    assert matcher_rules.match_push_subscription_command(
        _group_event(),
        {},
        messaging=_messaging_resources(tmp_path / "unsubscribe.sqlite"),
    )


def test_group_push_subscription_management_command_matches_regular_member(
    tmp_path: Path,
) -> None:
    assert matcher_rules.match_push_subscription_command(
        _group_event("推送管理", user_id=3003),
        {},
        messaging=_messaging_resources(tmp_path / "unsubscribe.sqlite"),
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
    assert matcher_rules.match_push_subscription_command(
        event, {}, messaging=messaging
    ) or matcher_rules.match_push_time_command(event, {}, messaging=messaging)
    assert catalog.claims_direct_input(
        CommandContext(_actor(SUPERUSER_ID), _private(SUPERUSER_ID)),
        messaging.feature_policy,
        text,
    )
    assert not _capture_ai_prompt(
        event,
        {},
        AiInputRoutingService(messaging.feature_policy, catalog),
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
    rule = (
        matcher_rules.match_push_subscription_command
        if text == "TD"
        else matcher_rules.match_push_time_command
    )
    assert rule(event, {}, messaging=messaging) is expected
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
async def test_configured_reply_and_menu_matchers_own_their_command_ids(
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
    runtime = build_test_runtime()
    registry = runtime.matcher_factory()

    contribution = plugin_contribution(
        config=config,
        features=runtime.features,
        references=runtime.onebot_references,
        service=messaging,
        activity_service=cast("ActivityService", object()),
        scheduler=cast("Scheduler", FakeScheduler()),
    )
    assert contribution.install is not None
    contribution.install(registry)
    registry.validate_command_catalog(_messaging_catalog(config))
    registrations = [
        registry.cooldown_registration(m) for m in registry.message_matchers
    ]
    assert ("command", "messaging.push_subscription") in registrations
    assert ("command", "messaging.push_time") in registrations
    assert len(registrations) == 2 + enabled * (configured + keyword)
    for text in ("示例", "包含示例的文字", "无关"):
        event = private_message_event(text, user_id=SUPERUSER_ID)
        matches = []
        for matcher in registry.message_matchers:
            state = dict(matcher._default_state)
            if await matcher.rule(cast("Bot", None), event, state):
                action = cast(
                    "MessageReplyAction", state[matcher_rules.MESSAGE_ACTION_KEY]
                )
                matches.append(
                    (action.messages, state.get(EXPLICIT_COMMAND_STATE_KEY, False))
                )
        expected = (
            [(["exact"], True)]
            if enabled and configured and text == "示例"
            else [(["keyword"], False)]
            if enabled and keyword and "示例" in text
            else []
        )
        assert matches == expected


@pytest.mark.asyncio
async def test_enabled_mention_reply_registers_after_commands_before_ai(
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
    runtime = build_test_runtime()
    registry = runtime.matcher_factory()
    contribution = plugin_contribution(
        config=config,
        features=runtime.features,
        references=runtime.onebot_references,
        service=messaging,
        activity_service=cast("ActivityService", object()),
        scheduler=cast("Scheduler", FakeScheduler()),
    )
    assert contribution.install is not None

    contribution.install(registry)

    registrations = [
        registry.cooldown_registration(matcher)
        for matcher in registry.message_matchers
    ]
    assert ("exempt", "configured mention reply") in registrations
    matcher = next(
        candidate
        for candidate in registry.message_matchers
        if registry.cooldown_registration(candidate)
        == ("exempt", "configured mention reply")
    )
    assert matcher.priority == runtime.matcher_priorities.mention_reply
    assert runtime.matcher_priorities.message_commands < matcher.priority
    assert matcher.priority < runtime.matcher_priorities.ai_chat

    event = group_message_event(
        user_id=2002,
        group_id=1001,
        self_id=1,
        message=Message([MessageSegment.at(1)]),
    )
    state = dict(matcher._default_state)
    assert await matcher.rule(cast("Bot", None), event, state)


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
        messaging.match_mention_reply(
            _mention_context(configured, _group(1001))
        )
        is None
    )


@pytest.mark.parametrize("flow", [PUSH_SUBSCRIPTION_FLOW, PUSH_TIME_FLOW])
def test_push_menu_reply_ownership_stays_local_to_its_session(flow: PromptFlow) -> None:
    event = group_message_event("TD", user_id=SUPERUSER_ID, group_id=2002)
    session_id = event_conversation_session_id(flow.namespace, event)
    check = flow.reply_check(session_id, "group")
    for text in ("0", "1", "2"):
        assert check(group_message_event(text, user_id=SUPERUSER_ID, group_id=2002))
    assert not check(group_message_event("1", user_id=1003, group_id=2002))
    assert not check(group_message_event("1", user_id=SUPERUSER_ID, group_id=2003))
    assert not check(private_message_event("1", user_id=SUPERUSER_ID))
    assert not check(group_message_event("TD", user_id=SUPERUSER_ID, group_id=2002))
    assert not check(group_message_event("23:00", user_id=SUPERUSER_ID, group_id=2002))
    assert not check(
        group_message_event(
            "1", user_id=SUPERUSER_ID, group_id=2002, reply_sender_user_id=1
        )
    )
    value_check = flow.reply_check(session_id, "group", selection=False)
    assert value_check(
        group_message_event("23:00", user_id=SUPERUSER_ID, group_id=2002)
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


def test_reply_cooldown_keys_distinguish_same_named_action_families() -> None:
    state = {
        matcher_rules.MESSAGE_ACTION_KEY: MessageKeywordReplyAction(
            id="same", keywords=["示例"], messages=["keyword"]
        )
    }
    assert _action_command_id("message")(None, state) == "message.same"
    assert _action_command_id("message.keyword")(None, state) == "message.keyword.same"
    with pytest.raises(KeyError):
        _action_command_id("message.keyword")(None, {})


@pytest.mark.asyncio
async def test_onebot_configured_reply_sends_messages_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    async def record(_matcher: object, message: str, **_kwargs: object) -> None:
        sent.append(message)

    monkeypatch.setattr(messaging_matchers, "send_matcher_message", record)
    monkeypatch.setattr(messaging_matchers, "finish_matcher_message", record)
    action = MessageCommandAction(
        id="sequence",
        commands=["连续回复"],
        messages=["第一条", "第二条", "第三条"],
    )
    await messaging_matchers.handle_message_command(
        cast("Matcher", object()),
        private_message_event("连续回复", user_id=SUPERUSER_ID),
        {matcher_rules.MESSAGE_ACTION_KEY: action},
        references=OneBotReferenceResolver(group_aliases={}, user_aliases={}),
    )
    assert sent == action.messages


@pytest.mark.asyncio
async def test_onebot_configured_reply_addresses_explicit_member_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_targets: list[tuple[int, ...]] = []

    async def record(
        _matcher: object,
        _message: str,
        *,
        at_user_ids: tuple[int, ...] | list[int],
        **_kwargs: object,
    ) -> None:
        sent_targets.append(tuple(at_user_ids))

    monkeypatch.setattr(messaging_matchers, "finish_matcher_message", record)
    action = MessageCommandAction(
        id="targeted",
        commands=["加群"],
        messages=["加群信息"],
        at_user_ids=[790],
    )
    event = group_message_event(
        message=Message("加群 ") + MessageSegment.at(789) + MessageSegment.at(789),
    )

    await messaging_matchers.handle_message_command(
        cast("Matcher", object()),
        event,
        {matcher_rules.MESSAGE_ACTION_KEY: action},
        references=OneBotReferenceResolver(group_aliases={}, user_aliases={}),
    )

    assert sent_targets == [(789, 790)]


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

    private_state: dict[str, object] = {}
    group_state: dict[str, object] = {}
    assert matcher_rules.match_message_command(
        private_message_event("activity", user_id=2001),
        private_state,
        messaging=messaging,
        interaction="direct",
    )
    assert matcher_rules.match_message_command(
        group_member_message_event("activity", user_id=2002, group_id=1001),
        group_state,
        messaging=messaging,
        interaction="direct",
    )
    private_action = cast(
        "MessageCommandAction",
        private_state[matcher_rules.MESSAGE_ACTION_KEY],
    )
    group_action = cast(
        "MessageCommandAction",
        group_state[matcher_rules.MESSAGE_ACTION_KEY],
    )
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
                keywords=["出出"],
                feature="text",
                messages=["关键词回复"],
            )
        ],
        group_policy={"1001": ["text"]},
    )

    exact_state: dict[str, object] = {}
    keyword_state: dict[str, object] = {}
    assert matcher_rules.match_message_command(
        group_member_message_event("出出", user_id=2002, group_id=1001),
        exact_state,
        messaging=messaging,
        interaction="direct",
    )
    assert matcher_rules.match_message_command(
        group_member_message_event("今天出出了", user_id=2002, group_id=1001),
        keyword_state,
        messaging=messaging,
        interaction="automatic",
    )
    exact_action = cast(
        "MessageCommandAction",
        exact_state[matcher_rules.MESSAGE_ACTION_KEY],
    )
    keyword_action = cast(
        "MessageKeywordReplyAction",
        keyword_state[matcher_rules.MESSAGE_ACTION_KEY],
    )
    assert exact_action.id == "exact_reply"
    assert keyword_action.id == "keyword_reply"


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

    action = messaging.match_mention_reply(
        _mention_context(configured, conversation)
    )

    assert action is not None
    assert action.messages == ["first", "second"]
    assert (
        messaging.match_mention_reply(
            _mention_context(_actor(2003), conversation)
        )
        is None
    )
    assert (
        messaging.match_mention_reply(
            _mention_context(configured, conversation, mentions_bot=False)
        )
        is None
    )


def test_onebot_mention_rule_uses_shared_mention_reply_matcher(
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
    state: dict[str, object] = {}
    event = group_message_event(
        user_id=2002,
        group_id=1001,
        self_id=1,
        message=Message([MessageSegment.at(1)]),
    )

    assert matcher_rules.match_mention_reply(event, state, messaging=messaging)
    action = cast(
        "MessageMentionReplyAction",
        state[matcher_rules.MESSAGE_ACTION_KEY],
    )
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
