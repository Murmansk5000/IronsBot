from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from ironsbot.config.models.messaging import PushUnsubscribeConfig
from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandCatalog,
    CommandContext,
    CommandContract,
)
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import (
    BinaryImagePart,
    DeliveryFailureKind,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    ReplyContext,
    SendResult,
    TextPart,
)
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.core.promotions import PromotionCatalog
from ironsbot.integrations.storage.player_bindings import SqlitePlayerBindingStore
from ironsbot.integrations.storage.push_subscriptions import PushUnsubscribeStore
from ironsbot.services.about import AboutService, about_command_contracts
from ironsbot.services.bilibili.outbound_delivery import (
    render_dynamic_content_message,
)
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.messaging.proactive_delivery import ProactiveMessageDelivery
from ironsbot.services.messaging.sendpic import SingleImageResult
from ironsbot.services.seer.autocard import AutocardEntry
from ironsbot.services.seer.autocard_media import AutocardMediaService
from ironsbot.services.seer.data_queries import DataQueryImageReply
from ironsbot.services.seer.peak import PeakQueryResult
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.seer.query_result import QueryReply
from tests.helpers.fake_official_platform import (
    RESTRICTED_CAPABILITIES,
    FakeOfficialPlatform,
)

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 9, 5, tzinfo=timezone.utc)
GROUP = ConversationRef(Platform.QQ_OFFICIAL, "group", "group:opaque/a")
MEMBER = ActorRef(Platform.QQ_OFFICIAL, "member:opaque", "member", GROUP.id)
TEXT = OutboundMessage((TextPart("result"),))
IMAGE = BinaryImagePart(b"test-image-payload", "image/png", "result.png")


@pytest.mark.asyncio
@pytest.mark.parametrize("with_image", [False, True])
async def test_seer_reply_uses_shared_content_without_platform_identity(
    *,
    with_image: bool,
) -> None:
    reply = QueryReply(
        leading_text="leading\n",
        image=IMAGE.content if with_image else None,
        image_error="image unavailable\n",
        text="description",
        complete=False,
    )
    message = reply.to_outbound()
    expected_middle = (
        BinaryImagePart(IMAGE.content, "image/png")
        if with_image
        else TextPart("image unavailable\n")
    )
    assert message.parts == (
        TextPart("leading\n"),
        expected_middle,
        TextPart("description"),
    )
    transport = FakeOfficialPlatform(NOW)
    result = await transport.reply(ReplyContext.from_message(_incoming()), message)
    assert result.delivered
    assert transport.attempts == [(GROUP, message)]
    assert len(transport.uploads) == int(with_image)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        DataQueryImageReply(b"preview", "缓存时间：2026-09-13").to_outbound(
            reference_url="https://example.test/preview"
        ),
        SingleImageResult(b"configured-image").to_outbound(),
        PeakQueryResult(image=b"peak-image").to_outbound(),
        PeakQueryResult(text="专家榜结果").to_outbound(),
        AutocardEntry(
            kind="card",
            item_id=1,
            name="测试牌",
            text="卡牌详情",
            image_key="card_1",
        ).to_outbound(),
    ],
)
async def test_seer_specialized_results_share_the_outbound_port(
    message: OutboundMessage,
) -> None:
    transport = FakeOfficialPlatform(NOW)

    result = await transport.reply(ReplyContext.from_message(_incoming()), message)

    assert result.delivered
    assert transport.attempts == [(GROUP, message)]
    assert len(transport.uploads) == sum(
        isinstance(part, BinaryImagePart) for part in message.parts
    )


@pytest.mark.asyncio
async def test_autocard_resolves_published_binary_before_restricted_delivery() -> None:
    class Images:
        async def fetch(
            self,
            kind: str,
            key: str,
            *,
            fallback: bool,
        ) -> bytes:
            assert (kind, key, fallback) == ("autocard_card", "card_7", False)
            return b"published-card"

    entry = AutocardEntry(
        kind="card",
        item_id=7,
        name="测试牌",
        text="卡牌详情",
        image_key="card_7",
    )
    message = await AutocardMediaService(Images()).outbound(entry)  # type: ignore[arg-type]
    transport = FakeOfficialPlatform(NOW)

    result = await transport.reply(ReplyContext.from_message(_incoming()), message)

    assert result.delivered
    assert transport.uploads == [IMAGE.__class__(b"published-card", "image/png")]


@pytest.mark.asyncio
async def test_bilibili_history_content_crosses_restricted_platform_port() -> None:
    item = {
        "id_str": "dynamic:opaque",
        "modules": {
            "module_dynamic": {
                "major": {
                    "opus": {
                        "summary": {"text": "动态正文"},
                        "pics": [{"url": "https://example.test/dynamic.png"}],
                    }
                }
            }
        },
    }
    message = render_dynamic_content_message(item)
    assert message is not None
    assert message.parts == (
        TextPart("动态正文"),
        RemoteImagePart("https://example.test/dynamic.png"),
    )
    transport = FakeOfficialPlatform(NOW)

    result = await transport.reply(ReplyContext.from_message(_incoming()), message)

    assert result.delivered
    assert transport.attempts == [(GROUP, message)]


@pytest.mark.asyncio
async def test_about_service_crosses_restricted_platform_port(tmp_path: Path) -> None:
    version_file = tmp_path / "__version__"
    version_file.write_text("v9.9.9\n", encoding="utf-8")
    transport = FakeOfficialPlatform(NOW)
    message = AboutService.from_version_file(version_file).message()

    result = await transport.reply(ReplyContext.from_message(_incoming()), message)

    assert result.delivered
    assert transport.attempts == [(GROUP, message)]
    assert isinstance(message.parts[0], TextPart)
    assert "版本：v9.9.9" in message.parts[0].text
    assert "OneBot" not in message.parts[0].text


def test_about_service_uses_unknown_version_when_file_is_missing(
    tmp_path: Path,
) -> None:
    message = AboutService.from_version_file(tmp_path / "missing").message()

    assert isinstance(message.parts[0], TextPart)
    assert "版本：未知" in message.parts[0].text


def _incoming() -> IncomingMessageRef:
    return IncomingMessageRef(
        platform=Platform.QQ_OFFICIAL,
        actor=MEMBER,
        conversation=GROUP,
        message_id="event:opaque",
        text="query",
        sequence="sequence:opaque",
        reply_deadline=NOW + timedelta(seconds=10),
    )


@pytest.mark.asyncio
async def test_reply_preserves_current_event_metadata_and_uploads() -> None:
    incoming = replace(_incoming(), reply_to_id="quoted:event")
    context = ReplyContext.from_message(incoming)
    transport = FakeOfficialPlatform(NOW)
    message = OutboundMessage((MentionPart(MEMBER), TextPart("result"), IMAGE))

    result = await transport.reply(context, message)

    assert result.delivered
    assert result.trace_id == "fake-trace-1"
    assert context.message_id == incoming.message_id != incoming.reply_to_id
    assert context.sequence == incoming.sequence
    assert context.reply_deadline == incoming.reply_deadline
    assert transport.replies == [context]
    assert transport.attempts == [(GROUP, message)]
    assert transport.uploads == [IMAGE]


@pytest.mark.asyncio
@pytest.mark.parametrize("elapsed", [10, 11])
async def test_expired_reply_never_uploads(elapsed: int) -> None:
    transport = FakeOfficialPlatform(NOW + timedelta(seconds=elapsed))
    result = await transport.reply(
        ReplyContext.from_message(_incoming()), OutboundMessage((IMAGE,))
    )
    assert result.error_code == "fake_reply_expired"
    assert transport.uploads == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("flag", "message", "code"),
    [
        ("supports_images", OutboundMessage((IMAGE,)), "images_denied"),
        (
            "supports_images",
            OutboundMessage((RemoteImagePart("https://example.test/image.png"),)),
            "images_denied",
        ),
        (
            "can_mention_members",
            OutboundMessage((MentionPart(MEMBER),)),
            "mentions_denied",
        ),
        ("can_reply_to_event", TEXT, "reply_denied"),
        ("supports_group_context", TEXT, "reply_denied"),
    ],
)
async def test_restricted_content_is_rejected_not_silently_removed(
    flag: str, message: OutboundMessage, code: str
) -> None:
    transport = FakeOfficialPlatform(
        NOW, capabilities=replace(RESTRICTED_CAPABILITIES, **{flag: False})
    )
    result = await transport.reply(ReplyContext.from_message(_incoming()), message)
    assert result.error_code == f"fake_{code}"
    assert transport.uploads == []


@pytest.mark.asyncio
async def test_member_mention_cannot_escape_group_scope() -> None:
    transport = FakeOfficialPlatform(NOW)
    foreign_member = replace(MEMBER, scope_id="another:group")
    result = await transport.reply(
        ReplyContext.from_message(_incoming()),
        OutboundMessage((IMAGE, MentionPart(foreign_member))),
    )
    assert result.error_code == "fake_mention_scope"
    assert transport.uploads == []


def _catalog() -> CommandCatalog:
    catalog = CommandCatalog()
    catalog.load(
        (
            PluginContribution(id="help", commands=help_command_contracts()),
            PluginContribution(id="about", commands=about_command_contracts()),
            PluginContribution(
                id="example",
                commands=(
                    CommandContract(
                        id="example.manage",
                        plugin_id="example",
                        section="Manage",
                        examples=("/manage",),
                        description="Manage this group",
                        access=(CommandAccess("group", "group_manager"),),
                    ),
                ),
            ),
        ),
        known_features={"help", "about"},
    )
    return catalog


def test_real_catalog_policy_uses_opaque_scoped_identities() -> None:
    catalog = _catalog()
    private_actor = ActorRef(Platform.QQ_OFFICIAL, "user:opaque")
    private = ConversationRef(Platform.QQ_OFFICIAL, "private", private_actor.id)
    features = FeatureService(
        {GROUP: frozenset({"help", "about"})},
        {private_actor: frozenset({"help"})},
        frozenset(),
    )
    context = CommandContext(MEMBER, GROUP)
    assert {c.id for c in catalog.available_for_context(context, features)} == {
        "help",
        "about",
    }
    assert {c.id for c in catalog.poke_candidates_for_context(context, features)} == {
        "help"
    }
    assert {
        c.id
        for c in catalog.available_for_context(
            replace(context, group_role="admin"), features
        )
    } == {"help", "about", "example.manage"}
    assert {
        c.id
        for c in catalog.available_for_context(
            CommandContext(private_actor, private), features
        )
    } == {"help"}
    foreign = replace(GROUP, id="another:group")
    assert (
        catalog.available_for_context(
            CommandContext(replace(MEMBER, scope_id=foreign.id), foreign), features
        )
        == ()
    )
    assert not features.is_actor_superuser(replace(MEMBER, platform=Platform.ONEBOT))
    assert catalog.available_for_context(
        context, features, ignored_plugins=("help",)
    ) == (*about_command_contracts(),)


def test_real_binding_repository_and_resolver_isolate_identity(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite"
    store = SqlitePlayerBindingStore(path)
    other_group = replace(MEMBER, scope_id="another:group")
    other_platform = replace(MEMBER, platform=Platform.ONEBOT)
    user = ActorRef(Platform.QQ_OFFICIAL, MEMBER.id)
    bindings = ((MEMBER, 123456), (other_group, 234567), (other_platform, 345678))
    for actor, player_id in bindings:
        store.bind(actor=actor, player_id=player_id, player_nick="example")
    reopened = SqlitePlayerBindingStore(path)
    resolver = PlayerIdResolver(
        lambda _reference, _conversation: None,
        lambda actor: reopened.get(actor).player_id,
    )
    for actor, player_id in bindings:
        conversation = ConversationRef(actor.platform, "group", actor.scope_id or "")
        incoming = replace(
            _incoming(), platform=actor.platform, actor=actor, conversation=conversation
        )
        context = MessageInputContext(incoming, mentions_bot=False)
        assert resolver.resolve(context, None).player_id == player_id
        mentioned = replace(incoming, direct_mentions=(actor,))
        assert (
            resolver.resolve(
                MessageInputContext(mentioned, mentions_bot=False), None
            ).player_id
            == player_id
        )
    assert reopened.get(user).player_id is None


def _delivery(
    transport: FakeOfficialPlatform, store: PushUnsubscribeStore
) -> ProactiveMessageDelivery:
    return ProactiveMessageDelivery(
        transport,
        FeatureService({}, {}, frozenset()),
        PromotionCatalog({}),
        store,
        PushUnsubscribeConfig(),
    )


@pytest.mark.asyncio
async def test_real_push_service_does_not_attempt_forbidden_proactive_send(
    tmp_path: Path,
) -> None:
    transport = FakeOfficialPlatform(NOW)
    delivery = _delivery(transport, PushUnsubscribeStore(tmp_path / "state.sqlite"))
    result = await delivery.send(TEXT, (GROUP,), action_name="test", interval_seconds=0)
    assert result.failed == (GROUP,)
    assert transport.attempts == []


@pytest.mark.asyncio
async def test_persisted_subscription_filters_only_selected_conversation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "state.sqlite"
    store = PushUnsubscribeStore(path)
    private = ConversationRef(Platform.QQ_OFFICIAL, "private", GROUP.id)
    store.unsubscribe(GROUP, "schedule", "example")
    reopened = PushUnsubscribeStore(path)
    assert not reopened.is_unsubscribed(
        replace(GROUP, platform=Platform.ONEBOT), "schedule"
    )
    transport = FakeOfficialPlatform(
        NOW, capabilities=replace(RESTRICTED_CAPABILITIES, can_send_proactively=True)
    )
    message = OutboundMessage((TextPart("result"), IMAGE))
    result = await _delivery(transport, reopened).send(
        message,
        (GROUP, private),
        action_name="test",
        interval_seconds=0,
        subscription_key="schedule",
    )
    assert result.succeeded == (private,)
    assert result.failed == ()
    hinted_message = OutboundMessage(
        (*message.parts, TextPart(f"\n\n{PushUnsubscribeConfig().hint}"))
    )
    assert transport.attempts == [(private, hinted_message)]
    assert transport.uploads == [IMAGE]
    assert not reopened.mark_daily_hint_sent(private, "push_subscription_hint")


@pytest.mark.asyncio
async def test_push_failure_preserves_diagnostics(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    transport = FakeOfficialPlatform(
        NOW,
        capabilities=replace(RESTRICTED_CAPABILITIES, can_send_proactively=True),
        failure=SendResult(
            delivered=False,
            error_code="fake_rejected",
            error_message="sensitive transport detail",
            failure_kind=DeliveryFailureKind.PERMANENT,
        ),
    )
    result = await _delivery(
        transport, PushUnsubscribeStore(tmp_path / "state.sqlite")
    ).send(OutboundMessage((IMAGE,)), (GROUP,), action_name="test", interval_seconds=0)
    assert result.failed == (GROUP,)
    assert "fake_rejected" in caplog.text
    assert "failure_kind=permanent" in caplog.text
    assert "trace_id=fake-trace-1" in caplog.text
    assert "sensitive transport detail" not in caplog.text
    assert transport.uploads == []
