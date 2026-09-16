# SPDX-License-Identifier: GPL-3.0-or-later


class ClientNotInitializedError(Exception): ...


class NotLoggedInError(Exception): ...


class DisconnectedError(Exception): ...


class SocketRecvError(Exception):
    def __init__(
        self,
        result_code: int,
        *,
        command_id: int | None = None,
        message: str = "",
    ) -> None:
        self.result_code = result_code
        self.command_id = command_id
        self.message = message

    def __str__(self) -> str:
        return self.message or f"请求失败：{self.result_code}"

    def __repr__(self) -> str:
        return (
            "SocketRecvError("
            f"result_code={self.result_code}, command_id={self.command_id}"
            ")"
        )
