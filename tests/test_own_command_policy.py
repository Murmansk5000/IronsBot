import subprocess
import sys
from dataclasses import replace

import pytest

from ironsbot.config.models.transport import SelfCommandsConfig
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
    policy.record_outbound(incoming)
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
        policy.record_outbound(replace(INPUT, text=f"demo command{index}"))
    newest = replace(INPUT, text="demo command4099")
    assert policy.accept(newest) is None
    assert policy.accept(replace(INPUT, text="demo command0")) is not None
    now = 1600.0
    assert policy.accept(newest) is not None


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
from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.services.own_commands import OwnAccountCommandPolicy
policy = OwnAccountCommandPolicy(SelfCommandsConfig(enabled=True, prefixes=['demo ']))
incoming = OwnAccountInput(
    '1', ConversationRef(Platform.ONEBOT, 'group', '456'), True, 'demo help'
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
