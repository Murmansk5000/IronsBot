from dataclasses import dataclass

from ironsbot.services.operations.headless_errors import (
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.errors import format_player_query_error


@dataclass(frozen=True)
class SocketHead:
    result: int


def test_format_player_query_error_for_missing_player() -> None:
    error = SocketRecvError(SocketHead(result=101105))

    assert (
        format_player_query_error(123456, error)
        == "❌ 米米号 123456 不存在或用户信息不可查询。"
    )


def test_format_player_query_error_for_unavailable_server() -> None:
    assert (
        format_player_query_error(123456, NotLoggedInError())
        == "❌ 米米号 123456 暂时查不了："
        "查询需要连接赛尔号游戏服务器；当前服务器维护或未开放，请稍后再试。"
    )
