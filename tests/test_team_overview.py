from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from ironsbot.config.models.seer import TeamResourceConfig
from ironsbot.core.messaging import DeliveryReceipt, MessageTarget, TargetSendSummary
from ironsbot.integrations.onebot.delivery import OneBotDelivery
from ironsbot.plugins.team.overview import TeamOverviewMenus
from ironsbot.runtime.prompts import PromptItem
from ironsbot.services.team.resource import (
    TeamOverviewItem,
    TeamResourceQueryError,
    TeamResourceResult,
    TeamResourceService,
    TeamResourceSubscriptionTarget,
    TeamResourceSubscriptionUpdate,
    format_team_overview,
)
from tests.helpers.onebot_events import group_message_event, private_message_event
from tests.test_team_resource_runtime import _service

FAILED_TEAM = 1234567
HEALTHY_TEAM = 1234568


def _subscribe(
    service: TeamResourceService, team_id: int, mentions: tuple[int, ...] = ()
) -> None:
    service._store.upsert(
        TeamResourceSubscriptionUpdate(456, team_id, "示例战队", 1000, mentions, 1)
    )


@pytest.mark.asyncio
async def test_overview_order_and_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(TeamResourceConfig(enabled=True), tmp_path / "state.sqlite")
    for team_id in (1234569, 1234567, 1234568):
        _subscribe(service, team_id)

    async def query(
        _self: TeamResourceService, team_id: int, **_kwargs: Any
    ) -> TeamResourceResult:
        if team_id == FAILED_TEAM:
            raise TeamResourceQueryError.timeout(team_id)
        return TeamResourceResult(team_id, "示例战队", "details", 500, 66)

    monkeypatch.setattr(TeamResourceService, "query", query)
    items = await service.query_overview(TeamResourceSubscriptionTarget("group", 456))
    assert [item.team_id for item in items] == [1234569, 1234567, 1234568]
    assert items[1].error
    assert "人数：66，资源数：500" in format_team_overview(items)


@pytest.mark.asyncio
async def test_notices_merge_thresholds_mentions_and_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(TeamResourceConfig(enabled=True), tmp_path / "state.sqlite")
    _subscribe(service, 1234569, (101, 102))
    _subscribe(service, 1234567, (102, 103))
    _subscribe(service, 1234568)
    sent: list[Any] = []
    recorded: list[Any] = []
    service.notice_observers.append(
        lambda receipt, items: recorded.append((receipt, items))
    )

    async def query(
        _self: TeamResourceService, team_id: int, **_kwargs: Any
    ) -> TeamResourceResult:
        return TeamResourceResult(
            team_id, "示例战队", "", 2000 if team_id == HEALTHY_TEAM else 500, 60
        )

    async def send(_self: Any, messages: Any, **kwargs: Any) -> TargetSendSummary:
        sent.extend(messages)
        target = messages[0][0]
        kwargs["receipt_handler"](DeliveryReceipt(target, 1, 99, "not_checked"))
        assert kwargs["subscription_key"] == "team_resource_subscription"
        return TargetSendSummary([target], [])

    monkeypatch.setattr(TeamResourceService, "query", query)
    monkeypatch.setattr(OneBotDelivery, "send_target_messages", send)
    await service.scan()
    assert len(sent) == 1
    assert sent[0][0].at_user_ids == (101, 102, 103)
    assert "1234568" not in sent[0][1]
    assert [item.team_id for item in recorded[0][1]] == [1234569, 1234567]


def _menus() -> TeamOverviewMenus:
    service = MagicMock()
    service.allows_target.return_value = True
    return TeamOverviewMenus(service, MagicMock(), 180)


def test_notification_anchor_scope_latest_and_expiry() -> None:
    menus = _menus()
    items = (TeamOverviewItem(1234567, "示例战队", 60, 500),)
    menus.record_notice(
        DeliveryReceipt(MessageTarget("group", 456), 1, 99, "not_checked"), items
    )
    event = group_message_event("1", reply_sender_user_id=1, reply_message_id=99)
    assert menus.match_notice(event, {})
    assert not menus.match_notice(group_message_event("1"), {})
    assert not menus.match_notice(
        group_message_event(
            "1", group_id=457, reply_sender_user_id=1, reply_message_id=99
        ),
        {},
    )
    assert not menus.match_notice(
        group_message_event(
            "1", self_id=2, reply_sender_user_id=1, reply_message_id=99
        ),
        {},
    )
    menus.record_notice(
        DeliveryReceipt(MessageTarget("group", 456), 1, 100, "not_checked"), items
    )
    assert not menus.match_notice(event, {})
    menus.notices[(1, "group", 456)].expires_at = 0
    assert not menus.match_notice(
        group_message_event("1", reply_sender_user_id=1, reply_message_id=100), {}
    )


def test_notification_private_and_feature_filter() -> None:
    menus = _menus()
    menus.record_notice(
        DeliveryReceipt(MessageTarget("private", 123), 1, 99, "not_checked"), ()
    )
    assert menus.match_notice(private_message_event("0"), {})
    cast("Any", menus.service).allows_target.return_value = False
    assert not menus.match_notice(private_message_event("0"), {})


@pytest.mark.asyncio
async def test_notification_exit_only_consumes_current_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menus = _menus()
    menus.record_notice(
        DeliveryReceipt(MessageTarget("group", 456), 1, 99, "not_checked"), ()
    )
    event = group_message_event("0", reply_sender_user_id=1, reply_message_id=99)
    state: dict[str, Any] = {}
    assert menus.match_notice(event, state)
    monkeypatch.setattr(
        "ironsbot.plugins.team.overview.finish_event_reply", AsyncMock()
    )
    await menus.handle_notice(MagicMock(), event, state)
    assert not menus.match_notice(event, {})
    other = group_message_event(
        "0", user_id=124, reply_sender_user_id=1, reply_message_id=99
    )
    assert menus.match_notice(other, {})


@pytest.mark.asyncio
async def test_menu_reuses_details_and_keeps_selection_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menus = _menus()
    menus.query.query = AsyncMock(return_value="战队完整详情")
    enter = AsyncMock()
    send = AsyncMock()
    monkeypatch.setattr("ironsbot.plugins.team.overview.enter_prompt", enter)
    monkeypatch.setattr("ironsbot.plugins.team.overview.send_event_reply", send)
    matcher = MagicMock()
    event = group_message_event("战队")
    items = (
        TeamOverviewItem(1234567, "示例甲", 60, 500),
        TeamOverviewItem(1234568, "示例乙", 61, 600),
    )
    await menus.open(matcher, event, items)
    for item in items:
        await menus.select(PromptItem(item.name, "", item), matcher, event)
    assert enter.await_count == 1
    assert send.await_count == len(items)
    assert [call.args[0] for call in menus.query.query.await_args_list] == [
        (1234567,),
        (1234568,),
    ]


@pytest.mark.asyncio
async def test_notice_query_waits_for_prompt_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    menus = _menus()
    query = AsyncMock(return_value="详情")
    menus.query.query = query

    async def enter(*_args: Any, **kwargs: Any) -> None:
        query.assert_not_awaited()
        rendered = await kwargs["prompt_message"]
        assert "1234567" in rendered
        query.assert_awaited_once()

    monkeypatch.setattr("ironsbot.plugins.team.overview.enter_prompt", enter)
    monkeypatch.setattr("ironsbot.plugins.team.overview.send_event_reply", AsyncMock())
    item = TeamOverviewItem(1234567, "示例战队", 60, 500)
    await menus.open(MagicMock(), group_message_event("1"), (item,), first_item=item)
