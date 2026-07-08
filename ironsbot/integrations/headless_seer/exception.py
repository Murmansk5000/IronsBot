# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Any


class ConnectError(Exception): ...


class ClientNotInitializedError(Exception): ...


class NotLoggedInError(Exception): ...


class DisconnectedError(Exception): ...


class SocketRecvError(Exception):
    def __init__(
        self,
        head: Any,
        message: str = "",
    ) -> None:
        self.head = head
        self.message = message

    def __str__(self) -> str:
        return self.__repr__()

    def __repr__(self) -> str:
        return f"SocketRecvError(head={self.head}, message={self.message or '无'})"
