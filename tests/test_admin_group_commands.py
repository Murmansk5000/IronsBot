from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic import ValidationError

from ironsbot.config.models.settings import BotConfig
from ironsbot.core.command_catalog import (
    CommandAccess,
    CommandCatalog,
    CommandCatalogError,
    CommandContract,
)
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.message_input import MessageInputContext
from ironsbot.core.platform import (
    ActorRef,
    ConversationRef,
    IncomingMessageRef,
    Platform,
)
from ironsbot.core.plugin_install import PluginContribution
from ironsbot.services.ai.input_routing import AiInputRoutingService
from ironsbot.services.messaging.addressed_input import AddressedInputHintService
from ironsbot.services.operations.server_status import ServerStatusResult
from ironsbot.services.operations.server_status_commands import (
    server_status_command_contracts,
)
from ironsbot.services.portable_commands import PortableCommandRouter
from ironsbot.services.portable_operational_commands import (
    build_portable_server_status_operations,
)

if TYPE_CHECKING:
    from ironsbot.services.operations.server_status import ServerStatusService


@pytest.mark.parametrize("value", [False, True])
def test_group_toggle_is_one_strict_boolean(*, value: bool) -> None:
    assert BotConfig().admin_commands_in_groups
    assert BotConfig(admin_commands_in_groups=value).admin_commands_in_groups is value
    for invalid in ("both", "private", "group", "false", 1):
        with pytest.raises(ValidationError):
            BotConfig.model_validate({"admin_commands_in_groups": invalid})


@pytest.mark.parametrize("platform", list(Platform))
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("role", ["superuser", "manager", "member", "blocked"])
@pytest.mark.asyncio
async def test_headless_status_uses_shared_group_toggle_and_keeps_private_access(
    platform: Platform, *, enabled: bool, private: bool, role: str
) -> None:
    actor = ActorRef(platform, "101")
    conversation = ConversationRef(
        platform, "private" if private else "group", "101" if private else "456"
    )
    grants = (
        frozenset({"blacklist"})
        if role == "blocked"
        else frozenset({"server_status_query"})
    )
    features = FeatureService(
        {conversation: grants},
        {actor: grants},
        frozenset({actor}) if role in {"superuser", "blocked"} else frozenset(),
    )
    catalog = CommandCatalog(admin_commands_in_groups=enabled)
    catalog.load(
        (
            PluginContribution(
                id="server_status", commands=server_status_command_contracts()
            ),
        ),
        known_features={"server_status_query"},
    )
    service = Mock(
        query_normal=AsyncMock(return_value=ServerStatusResult("normal")),
        query_admin=AsyncMock(return_value=ServerStatusResult("admin")),
        query_headless_instances=AsyncMock(
            return_value=ServerStatusResult("instances")
        ),
    )
    router = PortableCommandRouter(
        catalog,
        build_portable_server_status_operations(cast("ServerStatusService", service)),
        features,
        ai=Mock(),
        ai_input_routing=AiInputRoutingService(features, catalog),
        addressed_input_hints=AddressedInputHintService(),
    )
    context = MessageInputContext(
        IncomingMessageRef(
            platform,
            actor,
            conversation,
            "event",
            "/无头状态",
            group_role="admin" if role == "manager" else "member",
        ),
        mentions_bot=False,
    )
    reply = await router.dispatch(context)
    allowed = role == "superuser" and (private or enabled)
    if allowed:
        assert reply is not None and "instances" in str(reply.message)
        service.query_headless_instances.assert_awaited_once()
    else:
        service.query_headless_instances.assert_not_awaited()
    service.query_admin.assert_not_awaited()


def test_management_flag_cannot_grant_regular_or_manager_access() -> None:
    for audience in ("regular", "group_manager"):
        with pytest.raises(CommandCatalogError, match="management"):
            CommandContract(
                id="manage",
                plugin_id="test",
                section="管理",
                examples=("/管理",),
                description="管理",
                management=True,
                access=(CommandAccess(audience=audience),),
            )


def test_regular_private_and_group_manager_contracts_are_not_rewritten() -> None:
    regular = CommandContract(
        id="regular",
        plugin_id="test",
        section="查询",
        examples=("查询",),
        description="查询",
    )
    private = replace(regular, id="private", access=(CommandAccess(scope="private"),))
    manager = replace(
        regular,
        id="manager",
        access=(CommandAccess(scope="group", audience="group_manager"),),
    )
    for enabled in (False, True):
        catalog = CommandCatalog(admin_commands_in_groups=enabled)
        catalog.load(
            (PluginContribution(id="test", commands=(regular, private, manager)),)
        )
        assert catalog.get("regular") is regular
        assert catalog.get("private") is private
        assert catalog.get("manager") is manager
