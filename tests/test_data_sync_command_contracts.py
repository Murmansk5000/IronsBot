import pytest

from ironsbot.services.operations.data_sync_commands import (
    FORCE_MANUAL_SYNC_COMMANDS,
    MANUAL_SYNC_COMMANDS,
    data_sync_command_contracts,
    is_force_data_sync_command,
    is_manual_data_sync_command,
)


@pytest.mark.parametrize(
    "text",
    tuple(
        f"/{command}"
        for command in (*MANUAL_SYNC_COMMANDS, *FORCE_MANUAL_SYNC_COMMANDS)
    ),
)
def test_manual_data_sync_parser_requires_an_explicit_slash(text: str) -> None:
    assert is_manual_data_sync_command(text)
    assert not is_manual_data_sync_command(text[1:])


@pytest.mark.parametrize(
    "text",
    tuple(f"/{command}" for command in FORCE_MANUAL_SYNC_COMMANDS),
)
def test_force_data_sync_parser_only_matches_force_commands(text: str) -> None:
    assert is_force_data_sync_command(text)


def test_data_sync_contract_examples_match_the_parser() -> None:
    commands = {command.id: command for command in data_sync_command_contracts()}

    assert commands["db_sync.update"].examples == tuple(
        f"/{command}" for command in MANUAL_SYNC_COMMANDS
    )
    assert commands["db_sync.force_update"].examples == tuple(
        f"/{command}" for command in FORCE_MANUAL_SYNC_COMMANDS
    )


def test_sync_alias_keeps_primary_command_and_rejects_direct_targets() -> None:
    commands = {command.id: command for command in data_sync_command_contracts()}
    assert commands["db_sync.update"].examples[0] == "/更新数据"
    assert commands["db_sync.force_update"].examples[0] == "/强制更新数据"
    assert is_manual_data_sync_command("/同步数据")
    assert is_force_data_sync_command("/强制同步数据")
    assert not is_manual_data_sync_command("/同步数据 游戏数据")
    assert not is_manual_data_sync_command("/强制同步数据 游戏数据")
