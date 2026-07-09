# SPDX-License-Identifier: GPL-3.0-or-later
from .type_hint import Buffer


def clac_crc8_val(body_bytes: Buffer) -> int:
    crc8_val = 0
    for b in body_bytes:
        crc8_val ^= b & 0xFF
    return crc8_val


def calculate_result(last_result: int, command_id: int, body: Buffer) -> int:
    crc8 = clac_crc8_val(body)
    return (
        last_result
        - int(last_result / 3)
        + 113
        + len(body) % 17
        + command_id % 23
        + crc8
        + 7
    )
