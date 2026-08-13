from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.extensions.contracts import PlayerLineupCachedReply
from ironsbot.extensions.player_lineup import PlayerLineupCacheServices

if TYPE_CHECKING:
    from pathlib import Path


def test_public_lineup_cache_round_trips_completed_reply(tmp_path: Path) -> None:
    cache = PlayerLineupCacheServices().open(str(tmp_path / "lineup.sqlite"))
    reply = PlayerLineupCachedReply(
        leading_text="玩家信息\n",
        text="",
        image=b"lineup-image",
    )

    cache.put(105023264, reply)

    assert cache.get(105023264) == reply
    assert cache.get(1) is None
