# SPDX-License-Identifier: MIT
from __future__ import annotations

from struct import unpack
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ironsbot.config.player_accounts import PlayerAccount
    from ironsbot.services.operations.headless import HeadlessGame

_GET_LUCKY_SKIN_WINDOW = 45866
_REQUEST = (
    0,
    0,
    18,
    203247,
    31101,
    31102,
    31103,
    31104,
    108937,
    108938,
    108939,
    108940,
    108941,
    108942,
    108943,
    401009,
    401010,
    401007,
    401008,
    351005,
    351004,
)
_SKIN_OFFSET = 8
_SKIN_COUNT = 4


class LuckySkinWindowError(RuntimeError):
    @classmethod
    def packet_request_failed(cls) -> LuckySkinWindowError:
        return cls("lucky skin window packet request failed")


class LuckySkinWindowNotConfiguredError(LuckySkinWindowError):
    pass


class LuckySkinWindowBindingError(LuckySkinWindowError):
    pass


class LuckySkinWindowPayloadError(LuckySkinWindowError):
    @classmethod
    def unaligned(cls) -> LuckySkinWindowPayloadError:
        return cls("skin window payload is not uint32 aligned")

    @classmethod
    def truncated(cls) -> LuckySkinWindowPayloadError:
        return cls("skin window payload is truncated")

    @classmethod
    def invalid_skin_ids(cls) -> LuckySkinWindowPayloadError:
        return cls("skin window payload has invalid skin IDs")


async def fetch_skin_ids(
    game: HeadlessGame,
    *,
    timeout_seconds: float,
    background: bool,
) -> tuple[int, ...]:
    try:
        with game.operations.track(
            "幸运橱窗检查",
            source="幸运橱窗专用会话",
            background=background,
        ):
            _head, payload = await game.send_and_wait(
                _GET_LUCKY_SKIN_WINDOW,
                *_REQUEST,
                timeout=timeout_seconds,
            )
    except (ConnectionError, TimeoutError) as error:
        raise LuckySkinWindowError.packet_request_failed() from error
    return parse_skin_ids(payload)


def parse_skin_ids(payload: bytes | bytearray | memoryview) -> tuple[int, ...]:
    data = bytes(payload)
    if len(data) % 4:
        raise LuckySkinWindowPayloadError.unaligned()
    values = unpack(f"!{len(data) // 4}I", data)
    if len(values) < _SKIN_OFFSET + _SKIN_COUNT:
        raise LuckySkinWindowPayloadError.truncated()
    skin_ids = tuple(values[_SKIN_OFFSET : _SKIN_OFFSET + _SKIN_COUNT])
    if len(skin_ids) != _SKIN_COUNT or any(skin_id <= 0 for skin_id in skin_ids):
        raise LuckySkinWindowPayloadError.invalid_skin_ids()
    return skin_ids


def required_password(account: PlayerAccount) -> str:
    if account.password is None:
        raise LuckySkinWindowNotConfiguredError
    return account.password
