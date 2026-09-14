import pytest
from pydantic import ValidationError

from ironsbot.config.models.operations import ServerStatusConfig
from ironsbot.services.operations.server_status_commands import (
    server_status_command_contracts,
)


def test_defaults_and_custom_catalog() -> None:
    assert {"开了吗", "关了吗"} <= set(ServerStatusConfig().commands)
    config = ServerStatusConfig(commands=[" 状态如何 ", "状态如何"])
    assert config.commands == ["状态如何"]
    command = next(
        c
        for c in server_status_command_contracts(tuple(config.commands))
        if c.id == "server_status.query"
    )
    assert command.examples == ("状态如何",)


@pytest.mark.parametrize("commands", [[], [""], ["/开服查询"], ["开服查询"]])
def test_invalid_commands(commands: list[str]) -> None:
    with pytest.raises(ValidationError):
        ServerStatusConfig(commands=commands)
