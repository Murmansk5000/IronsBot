import struct

from ironsbot.integrations.headless_seer.packets.user import UserInfo

USER_ID = 123456
TEAM_ID = 11


def _u32(value: int) -> bytes:
    return struct.pack("!I", value)


def _u8(value: int) -> bytes:
    return struct.pack("!B", value)


def test_extended_user_info_unpack_reads_optional_decoration_fields() -> None:
    data = b"".join(
        (
            _u32(USER_ID),
            b"tester".ljust(16, b"\x00"),
            _u32(1),
            _u32(2),
            _u32(3),
            _u8(0b10),
            _u32(4),
            _u32(5),
            _u32(6),
            _u32(1),
            _u32(7),
            _u32(8),
            _u32(9),
            _u32(10),
            _u32(TEAM_ID),
            _u32(1),
            _u32(0),
            _u32(12),
            _u8(13),
            _u32(14),
            _u32(15),
            _u8(1),
            _u8(0),
            _u32(16),
            _u32(17),
            _u32(18),
            _u32(19),
            _u32(20),
        )
    )

    info = UserInfo.unpack(data)

    assert info.user_id == USER_ID
    assert info.nick == "tester"
    assert info.is_extreme_nono
    assert info.team_id == TEAM_ID
    assert info.team_is_show
    assert info.clothes == ()
    assert info.is_friend
    assert not info.is_black
    assert info.decorate_list == (19, 20)
