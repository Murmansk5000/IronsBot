import nonebot

nonebot.init()

from ironsbot.services.bilibili.parser import (
    dynamic_suppression_reason,
    find_target_dynamics,
    parse_single_item,
)


def _dynamic_item(
    *,
    dynamic_id: str = "1211894957538803730",
    uid: int = 1310714247,
    name: str = "赛尔号",
    pub_ts: int = 1781004683,
    text: str = "恭喜@测试用户 获得【赛尔号周边礼包】！记得及时查看私信通知哦",
) -> dict:
    return {
        "id_str": dynamic_id,
        "modules": {
            "module_author": {
                "mid": uid,
                "name": name,
                "pub_ts": pub_ts,
            },
            "module_dynamic": {
                "major": {
                    "opus": {
                        "summary": {"text": text},
                        "pics": [
                            {"url": "http://i0.hdslb.com/bfs/new_dyn/test.jpg]"}
                        ],
                    }
                }
            },
        },
    }


def test_lottery_dynamic_is_suppressed() -> None:
    item = _dynamic_item()

    reason = dynamic_suppression_reason(
        item,
        ["恭喜.*获得", "记得及时查看私信通知"],
    )

    assert reason == "命中规则：恭喜.*获得"


def test_find_target_dynamics_filters_by_uid() -> None:
    target_item = _dynamic_item(uid=1310714247)
    other_item = _dynamic_item(uid=123456789)

    result = find_target_dynamics([target_item, other_item], [1310714247])

    assert result == [(1781004683, target_item)]


def test_link_mode_omits_content_and_images() -> None:
    item = _dynamic_item(text="这是一条普通动态，正文内容应该只在全文模式里出现")

    message = parse_single_item(item, 1781004683, mode="link")

    assert message is not None
    rendered = str(message)
    assert "传送门: https://t.bilibili.com/1211894957538803730" in rendered
    assert "正文内容" not in rendered
    assert "[CQ:image" not in rendered
