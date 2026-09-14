from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest

from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.outbound import OutboundMessage, TextPart
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.services.operations.data_sync import (
    ManualDataSyncAction,
    ManualDataSyncOption,
)
from ironsbot.services.operations.server_status import ServerStatusResult
from ironsbot.services.portable_operational_commands import (
    build_portable_data_sync_operations,
    build_portable_docker_operations,
    build_portable_meeting_operations,
    build_portable_server_status_operations,
)
from ironsbot.services.portable_query_sessions import PortableQuerySessions
from ironsbot.services.portable_reply import PortableReply

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from ironsbot.services.operations.data_sync import DataSyncService
    from ironsbot.services.operations.docker_update import DockerUpdateService
    from ironsbot.services.operations.server_status import ServerStatusService


@dataclass
class _FakeServerStatus:
    calls: list[str]

    async def query_normal(self) -> ServerStatusResult:
        self.calls.append("normal")
        return ServerStatusResult("normal status")

    async def query_admin(self) -> ServerStatusResult:
        self.calls.append("admin")
        return ServerStatusResult("admin status")

    async def query_headless_instances(self) -> ServerStatusResult:
        self.calls.append("instances")
        return ServerStatusResult("instance status")


class _FakeDataSync:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def prepare_manual(
        self,
        *,
        force: bool,
        progress: object,
    ) -> tuple[str, bool]:
        self.events.append(f"prepare:{force}")
        await cast("Callable[[str], Awaitable[None]]", progress)("checking data")
        self.events.append("checked")
        return "choose data action", True

    @staticmethod
    def manual_options(*, force: bool) -> tuple[ManualDataSyncOption, ...]:
        return (
            ManualDataSyncOption(
                "1",
                ManualDataSyncAction.SYNC_PUBLISHED,
                "sync published",
            ),
            ManualDataSyncOption(
                "2",
                ManualDataSyncAction.UPDATE_UPSTREAM,
                "force upstream" if force else "upstream",
            ),
        )

    async def run_manual(
        self,
        *,
        action: ManualDataSyncAction,
        force: bool,
        progress: object,
    ) -> str:
        self.events.append(f"run:{action.value}:{force}")
        await cast("Callable[[str], Awaitable[None]]", progress)("syncing data")
        self.events.append("synced")
        return "data synced"


class _FakeDockerUpdate:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def check_image_update(self, *, progress: object) -> str:
        self.events.append("prepare")
        await cast("Callable[[str], Awaitable[None]]", progress)("checking image")
        self.events.append("checked")
        return "image current"

    async def prepare_maintenance(self, choice: object) -> tuple[str, str]:
        self.events.append(f"prepare maintenance:{choice}")
        return "restarting", "process"

    async def execute_restart(self, action: object) -> None:
        self.events.append(f"restart:{action}")


def _context() -> MessageInputContext:
    actor = ActorRef(Platform.QQ_OFFICIAL, "user", account_id="bot")
    conversation = ConversationRef(
        Platform.QQ_OFFICIAL,
        "private",
        "user",
        account_id="bot",
    )
    return MessageInputContext(
        IncomingMessageRef(
            platform=Platform.QQ_OFFICIAL,
            actor=actor,
            conversation=conversation,
            message_id="message",
            text="",
        ),
        mentions_bot=False,
    )


def _text(message: object) -> str:
    assert isinstance(message, OutboundMessage)
    part = message.parts[0]
    assert isinstance(part, TextPart)
    return part.text


@pytest.mark.asyncio
async def test_portable_operational_queries_use_shared_services() -> None:
    service = _FakeServerStatus([])
    operations = {
        **build_portable_server_status_operations(
            cast("ServerStatusService", service)
        ),
        **build_portable_meeting_operations(
            "6638682008",
            "会议号：{meeting_number}\n{meeting_url}",
        ),
    }
    context = _context()

    normal = await operations["server_status.query"]("开服了吗", context)
    admin = await operations["server_status.admin_query"]("开服查询", context)
    instances = await operations["server_status.headless_instances"](
        "无头实例", context
    )
    meeting = await operations["meeting"]("会议", context)

    assert service.calls == ["normal", "admin", "instances"]
    assert _text(normal) == "normal status"
    assert _text(admin) == "admin status"
    assert _text(instances) == "instance status"
    assert _text(meeting) == (
        "会议号：663-868-2008\nhttps://meeting.tencent.com/p/6638682008"
    )


@pytest.mark.asyncio
async def test_portable_meeting_reports_missing_configuration() -> None:
    operations = build_portable_meeting_operations("", "{meeting_number}")

    result = await operations["meeting"]("会议", _context())

    assert "messaging.meeting.number" in _text(result)


@pytest.mark.asyncio
async def test_portable_data_sync_defers_check_and_selected_action() -> None:
    service = _FakeDataSync()
    sessions = PortableQuerySessions()
    operation = build_portable_data_sync_operations(
        cast("DataSyncService", service),
        sessions,
    )["db_sync.update"]
    context = _context()

    check = cast("PortableReply", await operation("更新数据", context))

    assert _text(check.message) == "checking data"
    assert service.events == ["prepare:False"]
    check.delivered()
    assert check.follow_up is not None
    menu = await check.follow_up()
    assert _text(menu) == "choose data action"
    assert service.events == ["prepare:False", "checked"]

    selected = await sessions.select("2", context, allow_deferred=True)
    assert isinstance(selected, PortableReply)
    assert _text(selected.message) == "syncing data"
    assert service.events[-1] == "run:update_upstream:False"
    selected.delivered()
    assert selected.follow_up is not None
    result = await selected.follow_up()

    assert _text(result) == "data synced"
    assert service.events[-1] == "synced"


@pytest.mark.asyncio
async def test_portable_force_data_sync_preserves_force_choice() -> None:
    service = _FakeDataSync()
    sessions = PortableQuerySessions()
    operation = build_portable_data_sync_operations(
        cast("DataSyncService", service),
        sessions,
    )["db_sync.force_update"]
    context = _context()

    check = cast("PortableReply", await operation("强制更新数据", context))
    check.delivered()
    assert check.follow_up is not None
    await check.follow_up()
    selected = await sessions.select("2", context, allow_deferred=True)

    assert isinstance(selected, PortableReply)
    assert service.events[-1] == "run:update_upstream:True"
    selected.delivered()
    assert selected.follow_up is not None
    await selected.follow_up()


@pytest.mark.asyncio
async def test_portable_docker_check_waits_for_initial_delivery() -> None:
    service = _FakeDockerUpdate()
    operation = build_portable_docker_operations(
        cast("DockerUpdateService", service),
        PortableQuerySessions(),
    )["docker_update.image_check"]

    reply = cast(
        "PortableReply",
        await operation("检查更新镜像", _context()),
    )

    assert _text(reply.message) == "checking image"
    assert service.events == ["prepare"]
    reply.delivered()
    assert reply.follow_up is not None
    result = await reply.follow_up()

    assert _text(result) == "image current"
    assert service.events == ["prepare", "checked"]


@pytest.mark.asyncio
async def test_portable_docker_restart_runs_only_after_preparation_reply() -> None:
    service = _FakeDockerUpdate()
    sessions = PortableQuerySessions()
    operation = build_portable_docker_operations(
        cast("DockerUpdateService", service),
        sessions,
    )["docker_update.restart"]
    context = _context()

    menu = await operation("/重启机器人", context)
    assert _text(menu) == (
        "选择机器人维护操作：\n"
        "1. 仅重启机器人\n"
        "2. 检查并更新镜像后重启\n"
        "0.【退出】\n\n"
        "输入序号后会立即执行。"
    )
    prepared = await sessions.select("1", context, allow_deferred=True)
    assert isinstance(prepared, PortableReply)
    assert _text(prepared.message) == "restarting"
    assert service.events == [
        "prepare maintenance:DockerMaintenanceChoice.RESTART_ONLY"
    ]

    prepared.delivered()
    assert prepared.follow_up is not None
    completed = await prepared.follow_up()
    assert _text(completed) == "机器人维护操作已提交。"
    assert service.events[-1] == "restart:process"
