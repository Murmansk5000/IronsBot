# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from typing import TYPE_CHECKING, Final, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

    from ..packet.packet import Deserializable

_T_Packet = TypeVar("_T_Packet", bound="Deserializable")


class PacketRegister(dict[int, type["Deserializable"]]):
    def register(
        self, cmd_id: int
    ) -> Callable[[type[_T_Packet]], type[_T_Packet]]:
        def wrapper(cls: type[_T_Packet]) -> type[_T_Packet]:
            self[cmd_id] = cls
            return cls

        return wrapper


packet_register: Final[PacketRegister] = PacketRegister()
