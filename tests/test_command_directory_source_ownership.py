from ironsbot.app.command_directory.operations import (
    data_sync_commands,
    server_status_commands,
)
from ironsbot.app.command_directory.plugins import (
    activity_commands,
    bilibili_commands,
)
from ironsbot.app.command_directory.seer import seer_query_commands
from ironsbot.plugins.bilibili.command_rules import (
    BILI_ACCOUNT_COMMANDS,
    BILI_PUSH_MODE_COMMANDS,
    DYNAMIC_MENU_COMMANDS,
    DYNAMIC_UPDATE_COMMANDS,
)
from ironsbot.plugins.operations.db_sync import (
    FORCE_MANUAL_SYNC_COMMANDS,
    MANUAL_SYNC_COMMANDS,
)
from ironsbot.plugins.operations.status.command_text import (
    ADMIN_SERVER_STATUS_COMMAND,
    BOT_RESTART_COMMANDS,
    DOCKER_CHECK_UPDATE_COMMANDS,
    DOCKER_UPDATE_COMMANDS,
    NORMAL_SERVER_STATUS_COMMAND,
)
from ironsbot.runtime.commands import CommandDescriptor
from ironsbot.services.activity.commands import (
    CURRENT_ACTIVITY_COMMANDS,
    SOON_ENDING_ACTIVITY_COMMANDS,
)
from ironsbot.services.seer.data_query_commands import (
    DATA_QUERY_HELP_EXAMPLES,
)


def _by_id(
    commands: tuple[CommandDescriptor, ...],
) -> dict[str, CommandDescriptor]:
    return {command.id: command for command in commands}


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
    assert bilibili["bilibili.refresh"].examples == (
        f"/{DYNAMIC_UPDATE_COMMANDS[0]}",
    )
    assert activity["activity.ending"].examples == SOON_ENDING_ACTIVITY_COMMANDS[:1]
    assert activity["activity.current"].examples == (
        f"/{CURRENT_ACTIVITY_COMMANDS[0]}",
    )


def test_operation_examples_use_matcher_command_sources() -> None:
    status = _by_id(server_status_commands())
    sync = _by_id(data_sync_commands())

    assert status["server_status.query"].examples == (NORMAL_SERVER_STATUS_COMMAND,)
    assert status["server_status.admin_query"].examples == (
        ADMIN_SERVER_STATUS_COMMAND,
    )
    assert status["server_status.restart"].examples == BOT_RESTART_COMMANDS
    assert status["server_status.image_update"].examples == DOCKER_UPDATE_COMMANDS
    assert status["server_status.image_check"].examples == DOCKER_CHECK_UPDATE_COMMANDS
    assert sync["db_sync.update"].examples == tuple(
        f"/{command}" for command in MANUAL_SYNC_COMMANDS
    )
    assert sync["db_sync.force_update"].examples == tuple(
        f"/{command}" for command in FORCE_MANUAL_SYNC_COMMANDS
    )


def test_data_query_examples_use_matcher_command_sources() -> None:
    seer = _by_id(seer_query_commands())

    assert seer["seer.data.query"].examples == DATA_QUERY_HELP_EXAMPLES
