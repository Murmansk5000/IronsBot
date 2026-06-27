from ironsbot.services.seer.query_help import seer_query_help_message


def test_seer_query_help_messages_include_examples() -> None:
    assert "群星牌布布种子" in seer_query_help_message("autocard")
    assert "群星牌榜" in seer_query_help_message("autocard")
    assert "回复“群星牌”" in seer_query_help_message("autocard")
    assert "谱尼技能" in seer_query_help_message("pet")
    assert "皮肤库贝萨" in seer_query_help_message("skin")
    assert "刻印圣战之无限" in seer_query_help_message("mintmark")
    assert "宝石强攻" in seer_query_help_message("gem")
