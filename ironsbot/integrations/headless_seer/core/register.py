# SPDX-License-Identifier: GPL-3.0-or-later
from collections.abc import Callable
from typing import TYPE_CHECKING, Final

from ..type_hint import T_Deserializable

if TYPE_CHECKING:
    from ..packet.packet import Deserializable


class PacketRegister(dict[int, type["Deserializable"]]):
    def register(
        self, cmd_id: int
    ) -> Callable[[type[T_Deserializable]], type[T_Deserializable]]:
        def wrapper(cls: type[T_Deserializable]) -> type[T_Deserializable]:
            self[cmd_id] = cls
            return cls

        return wrapper


packet_register: Final[PacketRegister] = PacketRegister()
