# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Annotated

import ironsbot.integrations.headless_seer.packet.fields as f
from ironsbot.integrations.headless_seer.packet.fields import size_by
from ironsbot.integrations.headless_seer.packet.packet import Deserializable

from ..as3bytearray import AS3ByteArray


class MainLoginPacket(Deserializable):
    password: Annotated[str, f.Unicode[32]]
    tmcid: f.UInt
    game_id: f.UInt
    _: f.UInt
    img_id: Annotated[AS3ByteArray, f.Char[16]]
    img_by: Annotated[AS3ByteArray, f.Char[6]]
    top_left_tmcid: Annotated[AS3ByteArray, f.Char[64]]
    channel: f.UInt
    device_id: Annotated[str, f.Unicode[16]]


# class SoUserInfo(BasePacket, Deserializable):
#     user_id: f.UInt
#     password: str = f.string_field(maxlen=8)
#     nick_name: str = f.string_field()
#     color: f.UInt
#     texture: f.UInt
#     clothes: Annotated[tuple[int, ...], f.Array[f.UInt, 5]]
#     custom_id: str = f.string_field()
#     last_user_id: f.UInt = 1
#     otherlogintype: Annotated[Literal[0, 1, 2, 3], f.UInt] = 0


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
