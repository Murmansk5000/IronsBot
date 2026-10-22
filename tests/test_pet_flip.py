from __future__ import annotations

import asyncio
import threading
from dataclasses import replace
from typing import Any, cast

import pytest

from ironsbot.config.models.features import FEATURE_BUNDLES
from ironsbot.core.command_catalog import CommandCatalog, command_context_from_input
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import BinaryImagePart, MentionPart, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.images import ImageKind, ImageSourceError
from ironsbot.services.seer.pet_flip import FlipPet, PetFlipService
from ironsbot.services.seer.type_calc import TypeCombinationSnapshot, TypeMatchupDataset


class Repository:
    def __init__(self, forward: float = 2, reverse: float = 0.5) -> None:
        first = TypeCombinationSnapshot(1, "火", 1, None)
        second = TypeCombinationSnapshot(2, "草", 2, None)
        self.pets: tuple[FlipPet, ...] = (
            FlipPet(10, "甲", 10, first),
            FlipPet(20, "乙", 20, second),
        )
        self.dataset = TypeMatchupDataset(
            (first, second),
            (),
            ((1, 1, 1), (2, 2, 1), (1, 2, forward), (2, 1, reverse)),
        )
        self.calls = 0
        self.thread_id: int | None = None

    def draw(self) -> tuple[tuple[FlipPet, ...], TypeMatchupDataset]:
        self.calls += 1
        self.thread_id = threading.get_ident()
        return self.pets, self.dataset


class Images:
    def __init__(self, *, failed: bool = False) -> None:
        self.failed = failed

    async def fetch(self, kind: ImageKind, key: str, *, fallback: bool = True) -> bytes:
        assert kind == "pet_head"
        assert not fallback
        if self.failed:
            message = "test asset unavailable"
            raise ImageSourceError(message)
        return b"image:" + key.encode()


def context(
    platform: Platform, ids: tuple[str, ...] = ("first", "second")
) -> MessageInputContext:
    account = "test-bot"
    return MessageInputContext(
        IncomingMessageRef(
            platform,
            ActorRef(platform, "caller", account_id=account),
            ConversationRef(platform, "group", "test-group", account_id=account),
            "test-message",
            "抛精灵",
            tuple(ActorRef(platform, value, account_id=account) for value in ids),
        ),
        mentions_bot=True,
    )


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    ("forward", "reverse", "winner"),
    [(2, 0.5, "first"), (0, 1, "second"), (1, 1, "second")],
)
def test_game_uses_shared_type_rules_and_stable_id_tiebreak(
    platform: Platform, forward: float, reverse: float, winner: str
) -> None:
    repository = Repository(forward, reverse)
    result = asyncio.run(
        PetFlipService(repository, Images()).play("抛精灵", context(platform))
    )
    mentions = [part.actor.id for part in result.parts if isinstance(part, MentionPart)]
    assert mentions == ["first", "second", winner]
    assert [
        part.content for part in result.parts if isinstance(part, BinaryImagePart)
    ] == [b"image:10", b"image:20"]
    assert repository.thread_id != threading.get_ident()


@pytest.mark.parametrize("platform", list(Platform))
def test_missing_avatars_preserve_both_summons_and_winner(platform: Platform) -> None:
    result = asyncio.run(
        PetFlipService(Repository(), Images(failed=True)).play(
            "抛精灵", context(platform)
        )
    )
    text = "".join(part.text for part in result.parts if isinstance(part, TextPart))
    assert "甲" in text and "乙" in text and "获胜" in text
    assert not any(isinstance(part, BinaryImagePart) for part in result.parts)
    assert "test asset" not in text


@pytest.mark.parametrize("platform", list(Platform))
def test_missing_relations_use_neutral_multiplier_without_blocking_game(
    platform: Platform,
) -> None:
    repository = Repository()
    repository.dataset = replace(repository.dataset, relations=())
    result = asyncio.run(
        PetFlipService(repository, Images()).play("抛精灵", context(platform))
    )
    mentions = [part.actor.id for part in result.parts if isinstance(part, MentionPart)]
    assert mentions == ["first", "second", "second"]
    assert any(isinstance(part, BinaryImagePart) for part in result.parts)


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize(
    "ids", [(), ("first",), ("first", "first"), ("first", "second", "third")]
)
def test_requires_exactly_two_distinct_structured_members(
    platform: Platform, ids: tuple[str, ...]
) -> None:
    repository = Repository()
    result = asyncio.run(
        PetFlipService(repository, Images()).play("抛精灵", context(platform, ids))
    )
    assert "两名不同成员" in str(result.parts)
    assert repository.calls == 0


@pytest.mark.parametrize("platform", list(Platform))
def test_filters_all_and_preserves_first_mention_order(
    platform: Platform,
) -> None:
    result = asyncio.run(
        PetFlipService(Repository(), Images()).play(
            "抛精灵", context(platform, ("all", "first", "first", "second"))
        )
    )
    assert [
        part.actor.id for part in result.parts if isinstance(part, MentionPart)
    ] == ["first", "second", "first"]


def test_too_few_pets_does_not_claim_a_winner() -> None:
    repository = Repository()
    repository.pets = ()
    result = asyncio.run(
        PetFlipService(repository, Images()).play("抛精灵", context(Platform.ONEBOT))
    )
    assert "足够" in str(result.parts)


def test_features_are_in_all_without_adding_to_seer_bundle() -> None:
    assert {"pet_flip", "push_topics"} <= FEATURE_BUNDLES["all"]
    assert "pet_flip" not in FEATURE_BUNDLES["seer"]


@pytest.mark.parametrize("platform", list(Platform))
def test_member_id_equal_to_appid_is_not_discarded(platform: Platform) -> None:
    result = asyncio.run(
        PetFlipService(Repository(), Images()).play(
            "抛精灵", context(platform, ("test-bot", "second"))
        )
    )
    assert [
        part.actor.id for part in result.parts if isinstance(part, MentionPart)
    ] == ["test-bot", "second", "test-bot"]


def test_onebot_adapter_excludes_bot_before_shared_game() -> None:
    from nonebot.adapters.onebot.v11 import Message, MessageSegment

    from tests.helpers.onebot_events import group_message_event
    from tests.helpers.onebot_inputs import message_input_context

    message = (
        Message("抛精灵")
        + MessageSegment.at(1)
        + MessageSegment.at(11)
        + MessageSegment.at(22)
    )
    incoming = message_input_context(group_message_event(message=message, self_id=1))
    result = asyncio.run(
        PetFlipService(Repository(), Images()).play(incoming.text, incoming)
    )
    assert incoming.mentions_bot
    assert [
        part.actor.id for part in result.parts if isinstance(part, MentionPart)
    ] == ["11", "22", "11"]


def test_official_adapter_excludes_bot_before_shared_game() -> None:
    from qqbot_agent_sdk.event_parser import InboundEvent

    from ironsbot.integrations.qq_official.identity import qq_official_incoming_message

    event = InboundEvent(
        event_type="GROUP_AT_MESSAGE_CREATE",
        chat_scope="group",
        chat_id="test-group",
        user_id="caller",
        content="抛精灵",
        message_id="test-message",
        timestamp="2099-01-01T00:00:00+08:00",
        message_type=0,
        raw={
            "mentions": [
                {"is_you": True, "member_openid": "bot-openid"},
                {"member_openid": "first"},
                {"member_openid": "second"},
            ]
        },
    )
    incoming = MessageInputContext(
        qq_official_incoming_message(event, account_id="test-app"), mentions_bot=True
    )
    result = asyncio.run(
        PetFlipService(Repository(), Images()).play(incoming.text, incoming)
    )
    assert [
        part.actor.id for part in result.parts if isinstance(part, MentionPart)
    ] == ["first", "second", "first"]


@pytest.mark.parametrize("platform", list(Platform))
def test_command_catalog_enforces_feature_and_group_scope(platform: Platform) -> None:
    from types import SimpleNamespace

    contracts = seer_command_contracts(
        cast("Any", SimpleNamespace(has_reference_choices=lambda *_: False))
    )
    command = next(item for item in contracts if item.id == "seer.pet.flip")
    catalog = CommandCatalog()
    catalog.load(
        (PluginContribution(id="seer_query", commands=(command,)),),
        known_features=("pet_flip",),
    )
    message = context(platform)
    command_context = command_context_from_input(message)
    enabled = FeatureService(
        group_features={message.message.conversation: frozenset({"pet_flip"})},
        actor_features={},
        superusers=frozenset(),
    )
    disabled = FeatureService({}, {}, frozenset())
    assert catalog.claims_direct_input(command_context, enabled, "抛精灵")
    assert catalog.executable_for_context(command_context, disabled) == ()
    assert command in catalog.available_for_context(command_context, enabled)
    assert "抛精灵" in catalog.format_for_context(
        command_context, enabled, plugin_id="seer_query"
    )
    private_context = replace(
        command_context,
        conversation=ConversationRef(
            platform, "private", "caller", account_id="test-bot"
        ),
    )
    private_features = FeatureService(
        {}, {message.message.actor: frozenset({"pet_flip"})}, frozenset()
    )
    assert catalog.executable_for_context(private_context, private_features) == ()
