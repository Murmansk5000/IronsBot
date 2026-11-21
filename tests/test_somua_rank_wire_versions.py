from __future__ import annotations

import struct
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from ironsbot.integrations.headless_seer.rank import fetch_rank_page
from ironsbot.services.seer.rank_models import RankEntry
from ironsbot.services.seer.somua import SOMUA_RANK_KEY, parse_somua_rank_page
from ironsbot.services.seer.somua_models import SomuaRankEntry

if TYPE_CHECKING:
    from ironsbot.integrations.headless_seer.game import SeerGame


def _entry(player: int, score: int, *, expanded: bool) -> bytes:
    row = struct.pack("!II16s", player, score, "示例玩家".encode())
    if not expanded:
        return row
    return row + struct.pack("!3I", 111, 0, 333) + struct.pack("!27I", *range(27))


@pytest.mark.parametrize("expanded", [False, True])
def test_rank_record_versions_keep_all_rows_and_legacy_identity(
    *, expanded: bool
) -> None:
    payload = struct.pack("!I", 2) + _entry(700001, 90, expanded=expanded)
    payload += _entry(700002, 80, expanded=expanded)
    rows = parse_somua_rank_page(payload, 2)
    assert [(row.id, row.nick, row.score) for row in rows] == [
        (700001, "示例玩家", 90),
        (700002, "示例玩家", 80),
    ]
    if expanded:
        assert isinstance(rows[0], SomuaRankEntry)
        slots = rows[0].common_somua
        assert [slot.sequence for slot in slots] == [111, 0, 333]
        assert slots[0].parts.body == 0
        assert (
            slots[0].parts.surround,
            slots[1].parts.body,
            slots[2].parts.surround,
        ) == (8, 9, 26)
    else:
        assert type(rows[0]) is RankEntry


@pytest.mark.parametrize("extra", [b"", b"x"])
def test_zero_count_requires_exact_packet_end(extra: bytes) -> None:
    if extra:
        with pytest.raises(ValueError, match="长度"):
            parse_somua_rank_page(struct.pack("!I", 0) + extra, 1)
    else:
        assert parse_somua_rank_page(struct.pack("!I", 0), 1) == []


@pytest.mark.parametrize("size", [0, 1, 23, 25, 143, 145, 288])
def test_unrecognized_or_truncated_record_is_rejected(size: int) -> None:
    with pytest.raises(ValueError, match="长度"):
        parse_somua_rank_page(struct.pack("!I", 1) + bytes(size), 1)


def test_mixed_width_rows_are_not_treated_as_one_supported_version() -> None:
    payload = struct.pack("!I", 2) + _entry(700001, 90, expanded=False)
    payload += _entry(700002, 80, expanded=True)
    with pytest.raises(ValueError, match="长度"):
        parse_somua_rank_page(payload, 2)


def test_repeated_present_instance_is_rejected_but_zero_slots_are_allowed() -> None:
    row = bytearray(_entry(700001, 90, expanded=True))
    struct.pack_into("!3I", row, 24, 111, 111, 0)
    with pytest.raises(ValueError, match="实例"):
        parse_somua_rank_page(struct.pack("!I", 1) + row, 1)
    struct.pack_into("!3I", row, 24, 0, 0, 0)
    parsed = parse_somua_rank_page(struct.pack("!I", 1) + row, 1)
    assert isinstance(parsed[0], SomuaRankEntry)
    assert all(slot.sequence == 0 for slot in parsed[0].common_somua)


@pytest.mark.asyncio
async def test_adapter_preserves_expanded_record_without_additional_requests() -> None:
    from typing import cast

    body = struct.pack("!I", 1) + _entry(700001, 90, expanded=True)
    game = AsyncMock()
    game.send_and_wait.return_value = (None, body)
    rows = await fetch_rank_page(
        cast("SeerGame", game), key=SOMUA_RANK_KEY, sub_key=1, start=1000, end=1000
    )
    assert isinstance(rows[0], SomuaRankEntry)
    assert tuple(slot.sequence for slot in rows[0].common_somua) == (111, 0, 333)
    game.send_and_wait.assert_awaited_once_with(45965, 1, 1000, 1000, timeout=15.0)
