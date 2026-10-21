import subprocess
import sys
from dataclasses import replace

import pytest

from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.outbound import DeliveryFailureKind, SendResult
from ironsbot.core.own_commands import OwnAccountCommand, OwnAccountInput
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.services.own_commands import OwnAccountCommandPolicy

INPUT = OwnAccountInput(
    account_id="1",
    conversation=ConversationRef(Platform.ONEBOT, "group", "456"),
    is_own_message=True,
    text="demo help",
)


@pytest.mark.parametrize(
    "incoming",
    [
        replace(INPUT, is_own_message=False),
        replace(INPUT, has_other_segments=True),
        replace(INPUT, mentioned_ids=("42",)),
        replace(INPUT, conversation=ConversationRef(Platform.ONEBOT, "private", "456")),
        replace(
            INPUT,
            conversation=ConversationRef(
                Platform.QQ_OFFICIAL, "group", "opaque", account_id="app"
            ),
        ),
    ],
)
def test_normalized_source_facts_cannot_grant_own_account_admission(
    incoming: OwnAccountInput,
) -> None:
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "])
    )
    assert policy.accept(incoming) is None


def test_admission_is_pure_and_does_not_hold_a_second_message_id_ledger() -> None:
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "])
    )
    assert policy.accept(INPUT) == OwnAccountCommand("help")
    assert policy.accept(INPUT) == OwnAccountCommand("help")


@pytest.mark.parametrize("text", ["demo help", "绑定米米号123456"])
def test_every_accepted_outbound_shape_is_guarded_against_echo(text: str) -> None:
    binding = text.startswith("绑定")
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=not binding, prefixes=["demo "])
    )
    incoming = replace(INPUT, text=text, mentioned_ids=("42",) if binding else ())
    assert policy.accept(incoming) is not None
    echo = policy.begin_outbound(incoming)
    policy.finish_outbound(echo, SendResult(delivered=True, message_id="1"))
    assert policy.accept(incoming) is None
    assert policy.accept(replace(incoming, account_id="2")) is not None
    assert (
        policy.accept(
            replace(incoming, conversation=replace(incoming.conversation, id="457"))
        )
        is not None
    )
    if binding:
        assert policy.accept(replace(incoming, mentioned_ids=("43",))) is not None
    else:
        assert policy.accept(replace(incoming, text="demo about")) is not None


def test_echo_retention_is_bounded_and_expires_without_sleeping() -> None:
    now = 1000.0
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "]), clock=lambda: now
    )
    for index in range(4100):
        echo = policy.begin_outbound(replace(INPUT, text=f"demo command{index}"))
        policy.finish_outbound(echo, SendResult(delivered=True, message_id="1"))
    newest = replace(INPUT, text="demo command4099")
    assert policy.accept(newest) is None
    assert policy.accept(replace(INPUT, text="demo command0")) is not None
    now = 1600.0
    assert policy.accept(newest) is not None


@pytest.mark.parametrize(
    "result,retained",
    [
        (SendResult(delivered=True, message_id="1"), True),
        (SendResult(delivered=False, attempted=False, error_code="not_sent"), False),
        *(
            (SendResult(delivered=False, error_code="failure", failure_kind=kind), keep)
            for kind, keep in (
                (DeliveryFailureKind.PERMANENT, False),
                (DeliveryFailureKind.RETRYABLE, False),
                (DeliveryFailureKind.TRANSPORT_UNAVAILABLE, False),
                (DeliveryFailureKind.UNCERTAIN, True),
            )
        ),
        (SendResult(delivered=False, error_code="unclassified"), True),
        (None, True),
    ],
)
def test_echo_reservation_settles_once_from_structured_receipt(
    result: SendResult | None, *, retained: bool
) -> None:
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "])
    )
    echo = policy.begin_outbound(INPUT)
    assert policy.accept(INPUT) is None
    policy.finish_outbound(echo, result)
    assert (policy.accept(INPUT) is None) is retained
    policy.finish_outbound(
        echo,
        SendResult(
            delivered=not retained,
            message_id="late" if not retained else None,
            error_code="late" if retained else None,
        ),
    )
    assert (policy.accept(INPUT) is None) is retained


@pytest.mark.parametrize("success_first", [False, True])
@pytest.mark.parametrize("retained", [False, True])
def test_overlapping_identical_sends_cannot_remove_each_others_echo(
    *, success_first: bool, retained: bool
) -> None:
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "])
    )
    first = policy.begin_outbound(INPUT)
    second = policy.begin_outbound(INPUT)
    failed = SendResult(
        delivered=False,
        error_code="rejected",
        failure_kind=DeliveryFailureKind.PERMANENT,
    )
    success = SendResult(delivered=True, message_id="sent") if retained else failed
    policy.finish_outbound(first, success if success_first else failed)
    assert policy.accept(INPUT) is None
    policy.finish_outbound(second, failed if success_first else success)
    assert (policy.accept(INPUT) is None) is retained


def test_late_echo_receipt_cannot_remove_a_new_generation() -> None:
    now = 100.0
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "]), clock=lambda: now
    )
    old = policy.begin_outbound(INPUT)
    now = 700.0
    fresh = policy.begin_outbound(INPUT)
    rejected = SendResult(delivered=False, attempted=False, error_code="not_sent")
    policy.finish_outbound(old, rejected)
    assert policy.accept(INPUT) is None
    policy.finish_outbound(fresh, rejected)
    assert policy.accept(INPUT) is not None


def test_echo_handles_cannot_settle_another_policys_record() -> None:
    first = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "])
    )
    second = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "])
    )
    own = first.begin_outbound(INPUT)
    other = second.begin_outbound(INPUT)
    rejected = SendResult(delivered=False, attempted=False, error_code="not_sent")
    first.finish_outbound(other, rejected)
    assert first.accept(INPUT) is None
    assert second.accept(INPUT) is None
    second.finish_outbound(other, rejected)
    assert second.accept(INPUT) is not None
    first.finish_outbound(own, rejected)
    assert first.accept(INPUT) is not None


def test_rejected_send_cannot_extend_an_earlier_successful_echo() -> None:
    now = 100.0
    policy = OwnAccountCommandPolicy(
        SelfCommandsConfig(enabled=True, prefixes=["demo "]), clock=lambda: now
    )
    first = policy.begin_outbound(INPUT)
    policy.finish_outbound(first, SendResult(delivered=True, message_id="1"))
    now = 650.0
    failed = policy.begin_outbound(INPUT)
    policy.finish_outbound(
        failed, SendResult(delivered=False, attempted=False, error_code="not_sent")
    )
    assert policy.accept(INPUT) is None
    now = 700.0
    assert policy.accept(INPUT) is not None


def test_public_own_account_policy_runs_without_nonebot() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
sys.modules['nonebot'] = None
from ironsbot.config.models.transport import SelfCommandsConfig
from ironsbot.core.own_commands import OwnAccountInput
from ironsbot.core.outbound import SendResult
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.services.own_commands import OwnAccountCommandPolicy
policy = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=['demo ']))
incoming = OwnAccountInput(
    '1', ConversationRef(Platform.ONEBOT, 'group', '456'), True, 'demo help'
)
assert policy.accept(incoming).text == 'help'
echo = policy.begin_outbound(incoming)
assert policy.accept(incoming) is None
policy.finish_outbound(
    echo, SendResult(delivered=False, attempted=False, error_code='not_sent')
)
assert policy.accept(incoming).text == 'help'
""",
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
