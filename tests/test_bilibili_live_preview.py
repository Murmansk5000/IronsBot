from datetime import datetime

import pytest

from ironsbot.core.bilibili import BiliAccountCategorySubscriptionConfig
from ironsbot.core.time import TZ_CN
from ironsbot.services.bilibili.categories import classify_dynamic
from ironsbot.services.bilibili.live_preview import parse_live_preview


def dynamic(
    text: str,
    *,
    published: str = "2030-11-11T17:00:00+08:00",
    uid: int = 700001,
    source: str = "synthetic-preview",
) -> dict:
    return {
        "id_str": source,
        "modules": {
            "module_author": {
                "mid": uid,
                "pub_ts": int(datetime.fromisoformat(published).timestamp()),
            },
            "module_dynamic": {"desc": {"text": text}},
        },
    }


@pytest.mark.parametrize(
    "text",
    [
        "直播预告：11月14日晚19:00开启直播",
        "本周四晚19:00开启直播，不见不散",
        "直播即将开启！\n\n11月14日晚19:00，不见不散！",
    ],
)
def test_absolute_and_publication_relative_times_agree(text: str) -> None:
    preview = parse_live_preview(dynamic(text))
    assert preview is not None
    assert preview.starts_at == datetime(2030, 11, 14, 19, tzinfo=TZ_CN).timestamp()


@pytest.mark.parametrize(
    ("text", "day", "hour", "minute"),
    [
        ("明晚七点半开播，直播不见不散", 12, 19, 30),
        ("明天下午3点30分开启直播", 12, 15, 30),
        ("后天晚上八点开启直播", 13, 20, 0),
        ("下周一19:00直播预告", 18, 19, 0),
    ],
)
def test_relative_chinese_clock(text: str, day: int, hour: int, minute: int) -> None:
    preview = parse_live_preview(dynamic(text))
    assert preview is not None
    assert (
        preview.starts_at
        == datetime(2030, 11, day, hour, minute, tzinfo=TZ_CN).timestamp()
    )


def test_cross_year_is_based_on_publication() -> None:
    preview = parse_live_preview(
        dynamic("1月1日19:00开启直播", published="2030-12-31T10:00:00+08:00")
    )
    assert (
        preview
        and preview.starts_at == datetime(2031, 1, 1, 19, tzinfo=TZ_CN).timestamp()
    )


@pytest.mark.parametrize(
    "text",
    [
        "今晚直播，晚点见",
        "11月14日开启直播",
        "直播预告：11月14日19:00或11月15日20:00",
        "11月14日活动开启。\n\n19:00开启直播",
        "今晚19:00直播",
    ],
)
def test_ambiguous_or_past_times_do_not_create_timer(text: str) -> None:
    preview = parse_live_preview(dynamic(text, published="2030-11-11T21:00:00+08:00"))
    assert preview is None or preview.starts_at is None


@pytest.mark.parametrize(
    "text",
    [
        "直播回放：11月14日19:00开播",
        "版本更新指引，直播即将开启",
        "11月14日19:00转播直播预告",
    ],
)
def test_not_own_live_announcement(text: str) -> None:
    assert parse_live_preview(dynamic(text)) is None


def test_forward_never_arms_authors_live_room() -> None:
    item = dynamic("11月14日19:00开启直播")
    item["orig"] = {"id_str": "somebody-else"}
    assert parse_live_preview(item) is None


@pytest.mark.parametrize("typed_forward", [False, True])
def test_self_forward_uses_only_new_body_and_publication(
    *, typed_forward: bool
) -> None:
    item = dynamic(
        "#虚构账号年末直播# 今晚19点，官方直播间准时开播！",
        published="2030-11-14T12:00:51+08:00",
        source="new-self-forward",
    )
    item["orig"] = dynamic(
        "直播预告：11月30日20:00开播",
        published="2030-11-10T10:00:00+08:00",
        source="old-preview",
    )
    if typed_forward:
        item["type"] = "DYNAMIC_TYPE_FORWARD"
    preview = parse_live_preview(item)
    assert preview is not None
    assert preview.source_id == item["id_str"]
    assert preview.published_at == item["modules"]["module_author"]["pub_ts"]
    assert preview.starts_at == datetime(2030, 11, 14, 19, tzinfo=TZ_CN).timestamp()
    assert classify_dynamic(item, None) == ("live_preview",)


@pytest.mark.parametrize("original_uid", [None, 0, -1, "unknown", 700002])
def test_forward_requires_confirmed_same_author(original_uid: object) -> None:
    item = dynamic("今晚19点开启直播")
    item["type"] = "DYNAMIC_TYPE_FORWARD"
    item["orig"] = dynamic("明晚19点开启直播")
    item["orig"]["modules"]["module_author"]["mid"] = original_uid
    assert parse_live_preview(item) is None


@pytest.mark.parametrize("outer_text", ["转发动态", "今晚直播，晚点见"])
def test_self_forward_never_borrows_original_schedule(outer_text: str) -> None:
    item = dynamic(outer_text)
    item["type"] = "DYNAMIC_TYPE_FORWARD"
    item["orig"] = dynamic("11月14日19:00开启直播")
    preview = parse_live_preview(item)
    assert preview is None or preview.starts_at is None


@pytest.mark.parametrize(
    ("text", "cancelled", "rescheduled"),
    [
        ("取消今晚直播", True, False),
        ("直播改为明晚20点开播", False, True),
    ],
)
def test_self_forward_retains_cancel_and_reschedule_semantics(
    text: str, *, cancelled: bool, rescheduled: bool
) -> None:
    item = dynamic(text)
    item["type"] = "DYNAMIC_TYPE_FORWARD"
    item["orig"] = dynamic("11月14日19:00开启直播")
    preview = parse_live_preview(item)
    assert preview is not None
    assert preview.cancelled == cancelled
    assert preview.rescheduled == rescheduled


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("今晚19点，年末直播准时开播！", ("live_preview",)),
        ("今晚19点，大师赛总决赛直播准时开播！", ("competition", "live_preview")),
        ("比赛赛程公布，请关注总决赛。", ("competition",)),
    ],
)
def test_narrow_competition_rules_preserve_independent_live_category(
    text: str, expected: tuple[str, ...]
) -> None:
    config = BiliAccountCategorySubscriptionConfig.model_validate(
        {
            "label": "虚构账号",
            "categories": {
                "competition": {
                    "label": "赛事",
                    "patterns": ["大师赛", "小师赛", "赛事", "比赛", "赛程", "总决赛"],
                }
            },
        }
    )
    item = dynamic(text)
    item["type"] = "DYNAMIC_TYPE_FORWARD"
    item["orig"] = dynamic("直播预告：11月14日19:00开启直播")
    assert classify_dynamic(item, config) == expected


def test_live_preview_category_does_not_require_custom_categories() -> None:
    assert classify_dynamic(dynamic("11月14日19:00开启直播"), None) == ("live_preview",)


def test_explicit_reschedule_uses_new_time_only() -> None:
    preview = parse_live_preview(
        dynamic("直播预告：原定11月14日19:00，改为11月15日20:00开播")
    )
    assert preview and preview.rescheduled
    assert preview.starts_at == datetime(2030, 11, 15, 20, tzinfo=TZ_CN).timestamp()
