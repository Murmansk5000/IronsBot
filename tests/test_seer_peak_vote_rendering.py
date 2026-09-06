from __future__ import annotations

from io import BytesIO
from typing import Any

import pytest
from PIL import Image

from ironsbot.services.seer.peak import PeakPetSnapshot
from ironsbot.services.seer.rank_models import RankEntry
from ironsbot.services.seer.rendering.peak_pool_vote import render_peak_pool_vote

EXPECTED_RENDER_WIDTH = 960
EXPECTED_TOTAL_VOTES = 742


def _png() -> bytes:
    output = BytesIO()
    Image.new("RGB", (2, 2), (32, 96, 160)).save(output, format="PNG")
    return output.getvalue()


class _Images:
    async def fetch(self, _kind: str, _key: str) -> bytes:
        return _png()


@pytest.mark.asyncio
async def test_vote_render_uses_dense_pool_metadata_and_percentages() -> None:
    captured: dict[str, Any] = {}

    async def render_html(*_args: object, **kwargs: Any) -> bytes:
        captured.update(kwargs["templates"])
        captured["max_width"] = kwargs["max_width"]
        return b"vote-image"

    result = await render_peak_pool_vote(
        _Images(),  # type: ignore[arg-type]
        render_html,  # type: ignore[arg-type]
        [
            {
                "title": "准限制级",
                "period": "9月4日12点 - 9月10日0点",
                "items": [
                    RankEntry(id=4000, nick="薇尔诗", score=379),
                    RankEntry(id=4468, nick="始皇帝·嬴政", score=363),
                ],
                "pets": [
                    PeakPetSnapshot(4000, "薇尔诗", 4000, 4),
                    PeakPetSnapshot(4468, "始皇帝·嬴政", 4468, 5),
                ],
            }
        ],
    )

    assert result == b"vote-image"
    assert captured["max_width"] == EXPECTED_RENDER_WIDTH
    pool = captured["pools"][0]
    assert pool["title"] == "准限制级"
    assert pool["period"] == "9月4日12点 - 9月10日0点"
    assert pool["total_votes"] == EXPECTED_TOTAL_VOTES
    assert [rank["percentage"] for rank in pool["ranks"]] == [51, 49]
