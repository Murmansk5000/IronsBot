from __future__ import annotations

import subprocess
import sys
from dataclasses import replace

import pytest

from ironsbot.integrations.onebot.ingress_facts import (
    OneBotMessageOrigin,
    onebot_admission_input,
)
from ironsbot.integrations.onebot.message_facts import OneBotMessageFacts


def _facts() -> OneBotMessageFacts:
    return OneBotMessageFacts(
        account_id="1",
        user_id="101",
        message_id="-12",
        text="执行",
        group_id="456",
        group_role="admin",
        reply_to_id="0",
        reply_sender_id="333",
        segments=({"type": "text", "data": {"text": "执行"}},),
        original_segments=(
            {"type": "at", "data": {"qq": "1"}},
            {"type": "at", "data": {"qq": "777"}},
            {"type": "at", "data": {"qq": "777"}},
            {"type": "text", "data": {"text": " 执行"}},
        ),
    )


@pytest.mark.parametrize("origin", list(OneBotMessageOrigin))
def test_one_snapshot_preserves_distinct_command_and_observation_facts(
    origin: OneBotMessageOrigin,
) -> None:
    facts = _facts()
    if origin is OneBotMessageOrigin.PRIVATE:
        facts = replace(facts, group_id=None)
    incoming = onebot_admission_input(facts, origin)
    context = incoming.context
    assert context is not None
    assert context.text == "执行"
    assert context.message.reply_to_id == "0"
    assert tuple(actor.id for actor in context.member_mentions) == ("777",)
    assert incoming.is_group_message is (origin is OneBotMessageOrigin.GROUP)
    assert incoming.own_input is None
    if origin is OneBotMessageOrigin.PRIVATE:
        assert incoming.observation is None
        assert context.message.group_role is None
    else:
        assert incoming.observation is not None
        assert incoming.observation.text == " 执行"
        assert incoming.observation.mentioned_qq_ids == ("1", "777")
        assert incoming.observation.message_id == "-12"
        assert context.message.group_role == "admin"


@pytest.mark.parametrize("own_sender", [False, True])
def test_only_sent_own_account_source_produces_own_command_facts(
    *,
    own_sender: bool,
) -> None:
    facts = replace(_facts(), user_id="1" if own_sender else "101")
    incoming = onebot_admission_input(facts, OneBotMessageOrigin.SENT_GROUP)
    assert incoming.is_group_message is own_sender
    assert (incoming.own_input is not None) is own_sender
    if incoming.own_input is not None:
        assert incoming.own_input.text == " 执行"
        assert incoming.own_input.mentioned_ids == ("1", "777", "777")
    received = onebot_admission_input(facts, OneBotMessageOrigin.GROUP)
    assert received.own_input is None


def test_reply_author_is_observation_fallback_not_a_direct_command_target() -> None:
    facts = replace(_facts(), original_segments=None)
    incoming = onebot_admission_input(facts, OneBotMessageOrigin.GROUP)
    assert incoming.context is not None and not incoming.context.member_mentions
    assert incoming.observation is not None
    assert incoming.observation.mentioned_qq_ids == ("333",)
    direct = onebot_admission_input(_facts(), OneBotMessageOrigin.GROUP)
    assert direct.observation is not None
    assert "333" not in direct.observation.mentioned_qq_ids


@pytest.mark.parametrize("origin", list(OneBotMessageOrigin))
def test_source_kind_and_conversation_must_agree(origin: OneBotMessageOrigin) -> None:
    facts = _facts()
    if origin is not OneBotMessageOrigin.PRIVATE:
        facts = replace(facts, group_id=None)
    with pytest.raises(ValueError):
        onebot_admission_input(facts, origin)


def test_projection_is_framework_free_and_executes_public_admission() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys, asyncio
sys.modules['nonebot'] = None
from ironsbot.integrations.onebot.ingress_facts import (
    OneBotMessageOrigin, onebot_admission_input,
)
from ironsbot.integrations.onebot.message_facts import OneBotMessageFacts
from ironsbot.services.onebot_admission import OneBotAdmissionService
from ironsbot.core.feature_policy import FeatureService
facts = OneBotMessageFacts('1', '101', '-12', 'help', group_id='456',
    segments=({'type': 'text', 'data': {'text': 'help'}},))
incoming = onebot_admission_input(facts, OneBotMessageOrigin.GROUP)
decision = asyncio.run(OneBotAdmissionService(
    messages_enabled=True, features=FeatureService({}, {}, frozenset()),
).decide(incoming))
assert decision.context is incoming.context
assert incoming.observation.text == 'help'
""",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
