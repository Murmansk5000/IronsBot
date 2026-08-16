from dataclasses import replace
from typing import Any, cast

import pytest

from ironsbot.services.seer.rendering.pet_info_presentation import present_pet_info
from tests.test_seer_pet_info_presentation import _assets, _snapshot


@pytest.mark.parametrize("source", ["analyze_desc", "desc", "formatting_adjustment"])
def test_boss_validity_tracks_each_segment(source: str) -> None:
    snapshot = _snapshot()
    description = (
        "[sprite name=dot1][color=#f35555]有效段[/color]|[sprite name=dot4]无效段|"
        "[sprite name=dot1]已有（boss无效）|普通段|"
        "[sprite name=dot2]其他标记|[sprite name=dot1]"
    )
    soulmark = replace(snapshot.soulmarks[0], desc="", pve_effective=True)
    soulmark = replace(soulmark, **{source: description})
    document = present_pet_info(replace(snapshot, soulmarks=(soulmark,)), _assets())
    values = cast("tuple[dict[str, Any], ...]", document.templates["soulmarks"])
    assert values[0]["desc"].split("<br>") == [
        '<b style="color:#f35555">有效段</b>（BOSS有效）',
        "无效段（BOSS无效）",
        "已有（boss无效）",
        "普通段",
        "其他标记",
        "",
    ]
