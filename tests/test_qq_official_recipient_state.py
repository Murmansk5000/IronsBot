from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ironsbot.core.platform import ConversationRef, Platform
from ironsbot.integrations.qq_official.recipient_state import (
    QQOfficialRecipientStateStore,
)

if TYPE_CHECKING:
    from pathlib import Path

    from ironsbot.core.platform import ConversationKind


def _conversation(
    kind: ConversationKind = "group",
    *,
    account_id: str = "app-a",
    recipient: str = "recipient-a",
) -> ConversationRef:
    return ConversationRef(
        Platform.QQ_OFFICIAL,
        kind,
        recipient,
        account_id=account_id,
    )


@pytest.mark.asyncio
async def test_group_rejection_is_persistent_and_account_scoped(
    tmp_path: Path,
) -> None:
    store = QQOfficialRecipientStateStore(tmp_path / "state.sqlite")

    assert await store.record_event(
        app_id="app-a",
        event_type="GROUP_MSG_REJECT",
        raw={"group_openid": "recipient-a"},
    )
    assert not await store.allows_proactive(_conversation())
    assert await store.allows_proactive(_conversation(account_id="app-b"))

    restarted = QQOfficialRecipientStateStore(tmp_path / "state.sqlite")
    assert not await restarted.allows_proactive(_conversation())


@pytest.mark.asyncio
async def test_receive_reenables_and_removal_disables_delivery(tmp_path: Path) -> None:
    store = QQOfficialRecipientStateStore(tmp_path / "state.sqlite")

    await store.record_event(
        app_id="app-a",
        event_type="GROUP_MSG_REJECT",
        raw={"group_openid": "recipient-a"},
    )
    await store.record_event(
        app_id="app-a",
        event_type="GROUP_MSG_RECEIVE",
        raw={"group_openid": "recipient-a"},
    )
    assert await store.allows_proactive(_conversation())

    await store.record_event(
        app_id="app-a",
        event_type="GROUP_DEL_ROBOT",
        raw={"group_openid": "recipient-a"},
    )
    assert not await store.allows_proactive(_conversation())

    await store.record_event(
        app_id="app-a",
        event_type="GROUP_ADD_ROBOT",
        raw={"group_openid": "recipient-a"},
    )
    assert await store.allows_proactive(_conversation())


@pytest.mark.asyncio
async def test_c2c_state_and_malformed_events_are_handled(tmp_path: Path) -> None:
    store = QQOfficialRecipientStateStore(tmp_path / "state.sqlite")
    private = _conversation("private")

    assert not await store.record_event(
        app_id="app-a",
        event_type="C2C_MSG_REJECT",
        raw={},
    )
    assert await store.allows_proactive(private)
    assert await store.record_event(
        app_id="app-a",
        event_type="C2C_MSG_REJECT",
        raw={"openid": "recipient-a"},
    )
    assert not await store.allows_proactive(private)
    assert await store.record_event(
        app_id="app-a",
        event_type="C2C_MSG_RECEIVE",
        raw={"openid": "recipient-a"},
    )
    assert await store.allows_proactive(private)


@pytest.mark.asyncio
async def test_recipient_state_is_isolated_by_conversation_kind(
    tmp_path: Path,
) -> None:
    store = QQOfficialRecipientStateStore(tmp_path / "state.sqlite")
    group = _conversation("group", recipient="shared-recipient")
    private = _conversation("private", recipient="shared-recipient")

    assert await store.record_event(
        app_id="app-a",
        event_type="GROUP_MSG_REJECT",
        raw={
            "timestamp": 1_796_889_600,
            "group_openid": "shared-recipient",
            "op_member_openid": "operator-a",
        },
    )
    assert not await store.allows_proactive(group)
    assert await store.allows_proactive(private)

    assert await store.record_event(
        app_id="app-a",
        event_type="C2C_MSG_REJECT",
        raw={"timestamp": 1_796_889_601, "openid": "shared-recipient"},
    )
    assert not await store.allows_proactive(group)
    assert not await store.allows_proactive(private)

    assert await store.record_event(
        app_id="app-a",
        event_type="C2C_MSG_RECEIVE",
        raw={"timestamp": 1_796_889_602, "openid": "shared-recipient"},
    )
    assert not await store.allows_proactive(group)
    assert await store.allows_proactive(private)
