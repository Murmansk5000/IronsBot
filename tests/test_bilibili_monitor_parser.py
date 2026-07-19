import nonebot

nonebot.init()

from ironsbot.plugins.bilibili.delivery import build_dynamic_message
from ironsbot.services.bilibili.parser import (
    dynamic_items_from_response,
    dynamic_suppression_reason,
    find_target_dynamics,
    target_dynamics_from_response,
)

TARGET_UID = 1310714247
OTHER_UID = 123456789
DEFAULT_PUB_TS = 1781004683
OLDER_PUB_TS = 100
MIDDLE_PUB_TS = 200
NEWER_PUB_TS = 300


def _dynamic_item(
    *,
    dynamic_id: str = "1211894957538803730",
    uid: int = TARGET_UID,
    name: str = "赛尔号",
    pub_ts: int = DEFAULT_PUB_TS,
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


def _dynamic_response(*items: object) -> dict:
    return {"data": {"items": list(items)}}


def test_lottery_dynamic_is_suppressed() -> None:
    item = _dynamic_item()

    reason = dynamic_suppression_reason(
        item,
        ["恭喜.*获得", "记得及时查看私信通知"],
    )

    assert reason == "命中规则：恭喜.*获得"


def test_find_target_dynamics_filters_by_uid() -> None:
    target_item = _dynamic_item(uid=TARGET_UID)
    other_item = _dynamic_item(uid=OTHER_UID)

    result = find_target_dynamics([target_item, other_item], [TARGET_UID])

    assert result == [(DEFAULT_PUB_TS, target_item)]


def test_dynamic_items_from_response_ignores_malformed_payloads() -> None:
    target_item = _dynamic_item()
    extra_item = {"id_str": "extra"}

    assert dynamic_items_from_response({}) == []
    assert dynamic_items_from_response({"data": {"items": "bad"}}) == []
    assert dynamic_items_from_response(
        _dynamic_response(target_item, "bad", None, extra_item)
    ) == [target_item, extra_item]


def test_target_dynamics_from_response_filters_and_sorts() -> None:
    older_item = _dynamic_item(dynamic_id="older", uid=TARGET_UID, pub_ts=OLDER_PUB_TS)
    newer_item = _dynamic_item(dynamic_id="newer", uid=TARGET_UID, pub_ts=NEWER_PUB_TS)
    other_item = _dynamic_item(dynamic_id="other", uid=OTHER_UID, pub_ts=MIDDLE_PUB_TS)
    response = _dynamic_response(newer_item, other_item, older_item)

    assert target_dynamics_from_response(response, [TARGET_UID]) == [
        (OLDER_PUB_TS, older_item),
        (NEWER_PUB_TS, newer_item),
    ]
    assert target_dynamics_from_response(
        response,
        [TARGET_UID],
        newest_first=True,
    ) == [
        (NEWER_PUB_TS, newer_item),
        (OLDER_PUB_TS, older_item),
    ]


def test_link_mode_omits_content_and_images() -> None:
    item = _dynamic_item(text="这是一条普通动态，正文内容应该只在全文模式里出现")

    message = build_dynamic_message(item, DEFAULT_PUB_TS, mode="link")

    assert message is not None
    rendered = str(message)
    assert "传送门: https://t.bilibili.com/1211894957538803730" in rendered
    assert "正文内容" not in rendered
    assert "[CQ:image" not in rendered
