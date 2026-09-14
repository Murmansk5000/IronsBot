from ironsbot.services.seer.rank_command_contracts import RANK_HELP_COMMANDS


def test_rank_help_uses_every_domain_help_alias() -> None:
    assert RANK_HELP_COMMANDS == (
        "榜单",
        "排行榜",
        "榜单帮助",
        "排行榜帮助",
        "有哪些榜单",
        "可用榜单",
    )
