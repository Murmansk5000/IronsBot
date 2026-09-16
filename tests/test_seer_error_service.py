from ironsbot.services.operations.headless_errors import (
    NotLoggedInError,
    SocketRecvError,
)
from ironsbot.services.seer.errors import format_player_query_error


def test_format_player_query_error_for_missing_player() -> None:
    error = SocketRecvError(101105)

    assert (
        format_player_query_error(123456, error)
        == "❌ 米米号 123456 不存在或用户信息不可查询。"
    )


def test_socket_recv_error_does_not_expose_packet_identity() -> None:
    error = SocketRecvError(
        10009,
        command_id=1001,
        message="请求失败：10009",
    )

    assert str(error) == "请求失败：10009"
    assert repr(error) == "SocketRecvError(result_code=10009, command_id=1001)"


def test_format_player_query_error_for_unavailable_server() -> None:
    assert (
        format_player_query_error(123456, NotLoggedInError())
        == "❌ 米米号 123456 暂时查不了："
        "查询需要连接赛尔号游戏服务器；当前服务器维护或未开放，请稍后再试。"
    )
