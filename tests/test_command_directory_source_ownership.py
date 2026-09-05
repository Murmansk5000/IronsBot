from collections.abc import Callable

import pytest

from ironsbot.core.command_catalog import CommandContext, CommandContract
from ironsbot.core.feature_policy import FeatureService
from ironsbot.core.platform import ActorRef, ConversationRef, Platform
from ironsbot.plugins.onebot.bilibili.command_rules import is_update_dynamic_command
from ironsbot.services.about_commands import about_command_contracts
from ironsbot.services.activity.command_contracts import activity_command_contracts
from ironsbot.services.activity.commands import (
    CURRENT_ACTIVITY_COMMANDS,
    NEW_ACTIVITY_COMMANDS,
    SOON_ENDING_ACTIVITY_COMMANDS,
    is_current_seer_activity_text,
    is_new_seer_activity_text,
    is_soon_ending_seer_activity_text,
)
from ironsbot.services.bilibili.command_contracts import bilibili_command_contracts
from ironsbot.services.bilibili.commands import (
    BILI_ACCOUNT_COMMANDS,
    BILI_PUSH_MODE_COMMANDS,
    DYNAMIC_MENU_COMMANDS,
    DYNAMIC_UPDATE_COMMANDS,
)
from ironsbot.services.help_commands import help_command_contracts
from ironsbot.services.operations.command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    BOT_RESTART_COMMANDS,
    DOCKER_CHECK_UPDATE_COMMANDS,
    DOCKER_UPDATE_COMMANDS,
    NORMAL_SERVER_STATUS_COMMANDS,
)
from ironsbot.services.operations.data_sync_commands import (
    FORCE_MANUAL_SYNC_COMMANDS,
    MANUAL_SYNC_COMMANDS,
    data_sync_command_contracts,
)
from ironsbot.services.operations.docker_commands import docker_command_contracts
from ironsbot.services.operations.server_status_commands import (
    server_status_command_contracts,
)
from ironsbot.services.pet_config_commands import pet_config_command_contracts
from ironsbot.services.seer.command_contracts import seer_command_contracts
from ironsbot.services.seer.data_query_commands import (
    DATA_QUERY_HELP_EXAMPLES,
)
from ironsbot.services.seer.lucky_skin_commands import (
    lucky_skin_window_command_contracts,
)
from ironsbot.services.seer.player_id_resolver import PlayerIdResolver
from ironsbot.services.team.resource_commands import team_resource_command_contracts
from tests.helpers.onebot_events import private_message_event


def _by_id(
    commands: tuple[CommandContract, ...],
) -> dict[str, CommandContract]:
    return {command.id: command for command in commands}


def _empty_player_id_resolver() -> PlayerIdResolver:
    return PlayerIdResolver(
        lambda _reference, _conversation: None,
        lambda _actor: None,
    )


def test_bilibili_and_activity_examples_use_matcher_command_sources() -> None:
    bilibili = _by_id(bilibili_command_contracts())
    activity = _by_id(activity_command_contracts())

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


def test_about_and_help_contracts_are_owned_by_application_services() -> None:
    about = _by_id(about_command_contracts())
    help_commands = _by_id(help_command_contracts())

    assert about["about"].examples == ("关于",)
    assert help_commands["help"].examples == ("帮助",)
    assert help_commands["help"].show_in_poke is True


def test_operation_examples_use_matcher_command_sources() -> None:
    status = _by_id(server_status_command_contracts())
    docker = _by_id(docker_command_contracts())
    sync = _by_id(data_sync_command_contracts())

    assert status["server_status.query"].examples == NORMAL_SERVER_STATUS_COMMANDS
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
    seer = _by_id(seer_command_contracts(_empty_player_id_resolver()))

    assert seer["seer.data.query"].examples == DATA_QUERY_HELP_EXAMPLES


def test_pet_config_contract_is_owned_by_its_domain_service() -> None:
    enabled = _by_id(pet_config_command_contracts(enabled=True))

    assert enabled["pet_config.query"].examples == (
        "雷伊配置",
        "配置雷伊",
        "4923配置",
    )
    assert pet_config_command_contracts(enabled=False) == ()


def test_team_resource_contract_is_owned_by_its_domain_service() -> None:
    commands = _by_id(team_resource_command_contracts(enabled=True))

    assert commands["team_resource.query"].examples == ("战队",)
    assert commands["team_resource.subscribe"].examples == ("订阅战队123456",)
    assert commands["team_resource.subscribe"].show_in_poke is True
    assert team_resource_command_contracts(enabled=False) == ()


def test_lucky_skin_window_contract_is_owned_by_its_domain_service() -> None:
    commands = _by_id(lucky_skin_window_command_contracts())

    assert commands["seer.lucky_skin_window.query"].examples == ("橱窗",)
    assert commands["seer.lucky_skin_window.watch.add"].examples == (
        "关注橱窗1400538 / 订阅橱窗1400538",
        "橱窗订阅名称",
    )


def test_seer_player_command_catalog_uses_shared_resolver_alias_recognition() -> None:
    resolver = PlayerIdResolver(
        lambda reference, _conversation: 105023264 if reference == "示例账号" else None,
        lambda _actor: None,
    )
    player_query = _by_id(seer_command_contracts(resolver))["seer.player.query"]
    assert player_query.routing_matcher is not None
    context = CommandContext(
        actor=ActorRef(Platform.ONEBOT, "1234567890"),
        conversation=ConversationRef(Platform.ONEBOT, "group", "987654321"),
    )

    assert player_query.routing_matcher("米米号示例账号", context)
    assert not player_query.routing_matcher("米米号未知账号", context)


@pytest.mark.parametrize("prefix", ["", "/", "//"])
@pytest.mark.parametrize(
    "command_id,commands,parser",
    [
        (
            "activity.ending",
            SOON_ENDING_ACTIVITY_COMMANDS,
            is_soon_ending_seer_activity_text,
        ),
        ("activity.new", NEW_ACTIVITY_COMMANDS, is_new_seer_activity_text),
        ("activity.current", CURRENT_ACTIVITY_COMMANDS, is_current_seer_activity_text),
    ],
)
def test_activity_ownership_matches_domain_prefix_rules(
    prefix: str,
    command_id: str,
    commands: tuple[str, ...],
    parser: Callable[[str], bool],
) -> None:
    actor = ActorRef(Platform.ONEBOT, "100")
    context = CommandContext(
        actor, ConversationRef(Platform.ONEBOT, "private", actor.id)
    )
    contract = _by_id(activity_command_contracts())[command_id]
    for command in commands:
        text = prefix + command
        assert contract.matches_direct_input(context, text) is parser(text)


@pytest.mark.parametrize("prefix", ["", "/", "//"])
@pytest.mark.parametrize("command", DYNAMIC_UPDATE_COMMANDS)
def test_bilibili_update_ownership_matches_actual_onebot_rule(
    prefix: str,
    command: str,
) -> None:
    actor = ActorRef(Platform.ONEBOT, "100")
    context = CommandContext(
        actor, ConversationRef(Platform.ONEBOT, "private", actor.id)
    )
    features = FeatureService({}, {}, frozenset({actor}))
    contract = _by_id(bilibili_command_contracts())["bilibili.refresh"]
    text = prefix + command
    event = private_message_event(text, user_id=int(actor.id))
    assert contract.matches_direct_input(context, text) is is_update_dynamic_command(
        features, event
    )
