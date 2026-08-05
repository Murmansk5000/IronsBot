from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.plugins.onebot.activity import command_descriptors as activity_commands
from ironsbot.plugins.onebot.bilibili import command_descriptors as bilibili_commands
from ironsbot.plugins.onebot.bilibili.command_rules import (
    BILI_ACCOUNT_COMMANDS,
    BILI_PUSH_MODE_COMMANDS,
    DYNAMIC_MENU_COMMANDS,
    DYNAMIC_UPDATE_COMMANDS,
)
from ironsbot.plugins.onebot.operations.db_sync import (
    FORCE_MANUAL_SYNC_COMMANDS,
    MANUAL_SYNC_COMMANDS,
)
from ironsbot.plugins.onebot.operations.db_sync import (
    command_descriptors as data_sync_commands,
)
from ironsbot.plugins.onebot.operations.docker_update import (
    command_descriptors as docker_update_commands,
)
from ironsbot.plugins.onebot.operations.server_status import (
    command_descriptors as server_status_commands,
)
from ironsbot.plugins.onebot.operations.status.command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    BOT_RESTART_COMMANDS,
    DOCKER_CHECK_UPDATE_COMMANDS,
    DOCKER_UPDATE_COMMANDS,
    NORMAL_SERVER_STATUS_COMMAND,
)
from ironsbot.runtime.commands import CommandContext, CommandDescriptor
from ironsbot.services.activity.commands import (
    CURRENT_ACTIVITY_COMMANDS,
    SOON_ENDING_ACTIVITY_COMMANDS,
)
from ironsbot.services.seer.command_contracts import seer_command_descriptors
from ironsbot.services.seer.data_query_commands import (
    DATA_QUERY_HELP_EXAMPLES,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver


def _by_id(
    commands: tuple[CommandDescriptor, ...],
) -> dict[str, CommandDescriptor]:
    return {command.id: command for command in commands}


def _empty_player_id_resolver() -> PlayerIdResolver:
    return PlayerIdResolver(
        lambda _reference, _conversation: None,
        lambda _actor: None,
    )


def test_bilibili_and_activity_examples_use_matcher_command_sources() -> None:
    bilibili = _by_id(bilibili_commands())
    activity = _by_id(activity_commands())

    assert bilibili["bilibili.dynamic"].examples == DYNAMIC_MENU_COMMANDS[:1]
    assert bilibili["bilibili.accounts"].examples == BILI_ACCOUNT_COMMANDS[:1]
    assert bilibili["bilibili.push_mode"].examples == (
        f"{BILI_PUSH_MODE_COMMANDS[0]} <账号> <内容|链接|默认>",
    )
    assert bilibili["bilibili.private_push_mode"].examples == (
        f"{BILI_PUSH_MODE_COMMANDS[0]} <账号> <内容|链接|默认>",
    )
    assert bilibili["bilibili.refresh"].examples == (f"/{DYNAMIC_UPDATE_COMMANDS[0]}",)
    assert activity["activity.ending"].examples == SOON_ENDING_ACTIVITY_COMMANDS[:1]
    assert activity["activity.current"].examples == (
        f"/{CURRENT_ACTIVITY_COMMANDS[0]}",
    )


def test_operation_examples_use_matcher_command_sources() -> None:
    status = _by_id(server_status_commands())
    docker = _by_id(docker_update_commands())
    sync = _by_id(data_sync_commands())

    assert status["server_status.query"].examples == (NORMAL_SERVER_STATUS_COMMAND,)
    assert status["server_status.admin_query"].examples == (
        ADMIN_SERVER_STATUS_COMMAND,
    )
    assert docker["docker_update.restart"].examples == BOT_RESTART_COMMANDS
    assert docker["docker_update.image_update"].examples == DOCKER_UPDATE_COMMANDS
    assert docker["docker_update.image_check"].examples == DOCKER_CHECK_UPDATE_COMMANDS
    assert sync["db_sync.update"].examples == tuple(
        f"/{command}" for command in MANUAL_SYNC_COMMANDS
    )
    assert sync["db_sync.force_update"].examples == tuple(
        f"/{command}" for command in FORCE_MANUAL_SYNC_COMMANDS
    )


def test_data_query_examples_use_matcher_command_sources() -> None:
    seer = _by_id(seer_command_descriptors(_empty_player_id_resolver()))

    assert seer["seer.data.query"].examples == DATA_QUERY_HELP_EXAMPLES


def test_seer_player_command_catalog_uses_shared_resolver_alias_recognition() -> None:
    resolver = PlayerIdResolver(
        lambda reference, _conversation: 105023264 if reference == "示例账号" else None,
        lambda _actor: None,
    )
    player_query = _by_id(seer_command_descriptors(resolver))["seer.player.query"]
    assert player_query.routing_matcher is not None
    context = CommandContext(
        actor=ActorRef(Platform.ONEBOT, "1234567890"),
        conversation=ConversationRef(Platform.ONEBOT, "group", "987654321"),
    )

    assert player_query.routing_matcher("米米号示例账号", context)
    assert not player_query.routing_matcher("米米号未知账号", context)
