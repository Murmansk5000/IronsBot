from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import replace
from unittest.mock import AsyncMock, Mock

import pytest

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import ExecutionIdentity
from ironsbot.core.own_commands import OwnAccountInput
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.identity_observation import OneBotGroupMessageObservation
from ironsbot.services.onebot_admission import (
    AdmissionRejection,
    OneBotAdmissionInput,
    OneBotAdmissionService,
)
from ironsbot.services.own_commands import OwnAccountCommandPolicy

_FEATURES = FeatureService({}, {}, frozenset())


def _input(source: str = "group") -> OneBotAdmissionInput:
    if source == "notice":
        return OneBotAdmissionInput()
    context = MessageInputContext(
        IncomingMessageRef(
            Platform.ONEBOT,
            ActorRef(Platform.ONEBOT, "101"),
            ConversationRef(
                Platform.ONEBOT, "private" if source == "private" else "group", "456"
            ),
            "message",
            "private-body",
        ),
        mentions_bot=False,
        execution_identity=ExecutionIdentity(Platform.ONEBOT, "1"),
    )
    observation = (
        None
        if source == "private"
        else OneBotGroupMessageObservation(
            sender_id=101,
            self_id=1,
            group_id=456,
            mentioned_qq_ids=(),
            text="private-body",
            message_id="message",
        )
    )
    return OneBotAdmissionInput(
        context=context, observation=observation, is_group_message=source == "group"
    )


def _own_input() -> OneBotAdmissionInput:
    frame = _input()
    assert frame.context is not None
    return replace(
        frame,
        observation=replace(frame.observation, sender_id=1)
        if frame.observation is not None
        else None,
        context=replace(
            frame.context,
            message=replace(
                frame.context.message, actor=ActorRef(Platform.ONEBOT, "1")
            ),
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["group", "sent", "private", "notice"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
async def test_observation_precedes_silence_and_only_group_messages_check_routes(
    source: str, *, enabled: bool, allowed: bool
) -> None:
    order: list[str] = []

    async def observe(_observation: OneBotGroupMessageObservation) -> None:
        order.append("observe")

    def route(_account: int, _conversation: ConversationRef) -> bool:
        order.append("route")
        return allowed

    observer = Mock(observe_onebot=AsyncMock(side_effect=observe))
    routing = Mock(allows_incoming=Mock(side_effect=route))
    decision = await OneBotAdmissionService(
        messages_enabled=enabled,
        features=_FEATURES,
        identity_observer=observer,
        routing=routing,
    ).decide(_input(source))
    expected = ["observe"] if source in {"group", "sent"} else []
    if enabled and source == "group":
        expected.append("route")
    assert order == expected
    assert decision.rejection == (
        AdmissionRejection.SILENT
        if not enabled
        else AdmissionRejection.ROUTING
        if source == "group" and not allowed
        else None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("binding", [False, True])
async def test_own_command_is_decided_before_routing_without_changing_authorization(
    *, binding: bool
) -> None:
    frame = _own_input()
    assert frame.context is not None
    own = OwnAccountInput(
        account_id="1",
        conversation=frame.context.message.conversation,
        is_own_message=True,
        text="绑定米米号123456" if binding else "demo help",
        mentioned_ids=("42",) if binding else (),
    )
    routing = Mock(allows_incoming=Mock(return_value=False))
    decision = await OneBotAdmissionService(
        messages_enabled=True,
        features=_FEATURES,
        routing=routing,
        self_commands=OwnAccountCommandPolicy(
            SelfCommandsConfig(enabled=not binding, prefixes=["demo "])
        ),
    ).decide(replace(frame, own_input=own))
    assert decision.rejection == (None if binding else AdmissionRejection.ROUTING)
    assert routing.allows_incoming.call_count == int(not binding)
    if binding:
        assert decision.own_command is not None and decision.own_command.admin_binding


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["observation", "routing", "own_policy"])
async def test_admission_faults_are_reported_and_never_granted(stage: str) -> None:
    error = RuntimeError("private-admission-detail")
    frame = _input()
    observer = Mock(
        observe_onebot=AsyncMock(side_effect=error if stage == "observation" else None)
    )
    routing = Mock(
        allows_incoming=Mock(side_effect=error if stage == "routing" else None)
    )
    own_policy = Mock(accept=Mock(side_effect=error))
    errors = Mock(report=AsyncMock())
    if stage == "own_policy":
        assert frame.context is not None
        frame = replace(
            _own_input(),
            own_input=OwnAccountInput(
                "1",
                frame.context.message.conversation,
                is_own_message=True,
                text="demo help",
            ),
        )
    result = await OneBotAdmissionService(
        messages_enabled=True,
        features=_FEATURES,
        identity_observer=observer,
        routing=routing,
        self_commands=own_policy,
        errors=errors,
    ).decide(frame)
    assert result.rejection is AdmissionRejection.FAILURE
    errors.report.assert_awaited_once_with(frame.context, error)


@pytest.mark.asyncio
async def test_admission_cancellation_does_not_report_or_continue() -> None:
    errors = Mock(report=AsyncMock())
    routing = Mock()
    service = OneBotAdmissionService(
        messages_enabled=False,
        features=_FEATURES,
        errors=errors,
        routing=routing,
        identity_observer=Mock(
            observe_onebot=AsyncMock(side_effect=asyncio.CancelledError)
        ),
    )
    with pytest.raises(asyncio.CancelledError):
        await service.decide(_input())
    errors.report.assert_not_awaited()
    routing.allows_incoming.assert_not_called()


def test_untrusted_partial_group_facts_require_normalized_context() -> None:
    with pytest.raises(ValueError):
        OneBotAdmissionInput(is_group_message=True)
    with pytest.raises(ValueError):
        OneBotAdmissionInput(context=_input("private").context, is_group_message=True)


def test_admission_runs_without_nonebot_imports() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys, asyncio
sys.modules['nonebot'] = None
from ironsbot.core.feature_policy import FeatureService
from ironsbot.services.onebot_admission import (
    OneBotAdmissionService, OneBotAdmissionInput,
)
result = asyncio.run(
    OneBotAdmissionService(
        messages_enabled=True, features=FeatureService({}, {}, frozenset())
    ).decide(OneBotAdmissionInput())
)
assert result.rejection is None
""",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "changed",
    [
        {"sender_id": 202},
        {"group_id": 999},
        {"self_id": 2},
    ],
)
def test_mirror_evidence_cannot_be_attached_to_another_message_source(
    changed: dict[str, int],
) -> None:
    frame = _input()
    assert frame.observation is not None
    with pytest.raises(ValueError, match="mirror evidence"):
        replace(frame, observation=replace(frame.observation, **changed))


def test_own_command_cannot_use_another_account_or_group() -> None:
    frame = _own_input()
    assert frame.context is not None
    wrong = OwnAccountInput(
        account_id="2",
        conversation=frame.context.message.conversation,
        is_own_message=True,
        text="绑定米米号123456",
        mentioned_ids=("42",),
    )
    with pytest.raises(ValueError, match="own command"):
        replace(frame, own_input=wrong)
