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
