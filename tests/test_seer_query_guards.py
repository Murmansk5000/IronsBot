# SPDX-License-Identifier: MIT
from ironsbot.services.seer.query_guards import is_rank_query_text


def test_rank_query_text_matches_rank_commands() -> None:
    assert is_rank_query_text("皮肤榜")
    assert is_rank_query_text("精灵图鉴榜")
    assert is_rank_query_text("套装榜")
    assert is_rank_query_text("5角刻印速度榜")
    assert is_rank_query_text("二角刻印攻击榜")
    assert is_rank_query_text("六角双攻榜")
    assert is_rank_query_text("刻印攻击榜")


def test_rank_query_text_does_not_block_pet_names_containing_rank_char() -> None:
    assert not is_rank_query_text("金榜灵童皮肤")
    assert not is_rank_query_text("金榜灵童技能")
