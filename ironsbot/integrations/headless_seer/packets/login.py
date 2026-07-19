# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Annotated

import ironsbot.integrations.headless_seer.packet.fields as f
from ironsbot.integrations.headless_seer.packet.fields import size_by
from ironsbot.integrations.headless_seer.packet.packet import Deserializable

from ..as3bytearray import AS3ByteArray


class SessionPackct(Deserializable):
    session: Annotated[bytes, f.Char[16]]
    _: f.UInt = 0


class ServerInfo(Deserializable):
    online_id: f.UInt
    user_cnt: f.UInt
    ip: Annotated[bytes, f.Char[16]]
    port: f.UShort
    friends: f.UInt

    def __post_init__(self) -> None:
        if self.user_cnt == 0:
            self.user_cnt = 3


class AllSvrListInfo(Deserializable):
    max_online_id: f.UInt
    vip_number: f.UInt
    online_time: f.UInt
    network_operator: f.UInt
    online_cnt: f.UInt
    svr_list: Annotated[list[ServerInfo], f.Array[size_by("online_cnt"), ServerInfo]]
    friend_data: Annotated[AS3ByteArray, f.Char[...]]


class RangeSvrInfo(Deserializable):
    online_cnt: f.UInt
    svr_list: Annotated[list[ServerInfo], f.Array[f.size_by("online_cnt"), ServerInfo]]
