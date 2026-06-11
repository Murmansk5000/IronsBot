from dataclasses import dataclass
from types import SimpleNamespace

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from pytest import MonkeyPatch

from ironsbot.shared.features import visibility


@dataclass(frozen=True)
class Action:
    enabled: bool
    feature: str


def _group_event(text: str = "帮助") -> GroupMessageEvent:
    return GroupMessageEvent(
        time=0,
        self_id=1,
        post_type="message",
        sub_type="normal",
        user_id=2,
        message_type="group",
        message_id=3,
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        group_id=4,
        sender={},
    )


def _config(
    *,
    ai_key: str = "",
    ai_intent_enabled: bool = True,
    team_ids: list[int] | None = None,
    group_actions: list[Action] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        ai_key=ai_key,
        ai_config=SimpleNamespace(intent_actions_enabled=ai_intent_enabled),
        team_ids=team_ids or [],
        msg_config=SimpleNamespace(
            group_commands=group_actions or [],
            group_schedules=[],
            private_commands=[],
            private_schedules=[],
        ),
    )


def test_original_plugins_are_hidden() -> None:
    assert not visibility.plugin_visible_for_event(
        "关于",
        "ironsbot.plugins.about",
        _group_event(),
    )


def test_always_visible_custom_help_is_shown() -> None:
    assert visibility.plugin_visible_for_event(
        "帮助",
        "ironsbot.custom_plugins.custom_help",
        _group_event(),
    )


def test_feature_module_visibility_uses_feature_service(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "is_event_feature_allowed",
        lambda _event, feature: feature == "seer",
    )

    assert visibility.plugin_visible_for_event(
        "扩展赛尔号查询",
        "ironsbot.custom_plugins.custom_get_seer_info",
        _group_event(),
    )
    assert not visibility.plugin_visible_for_event(
        "榜单",
        "ironsbot.custom_plugins.rank_help",
        _group_event(),
    )


def test_message_actions_visibility_reads_shared_config(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "get_shared_config",
        lambda: _config(group_actions=[Action(enabled=True, feature="text")]),
    )
    monkeypatch.setattr(
        visibility,
        "is_group_feature_allowed",
        lambda _user_id, _group_id, feature: feature == "text",
    )

    assert visibility.plugin_visible_for_event(
        "文本发送",
        "ironsbot.custom_plugins.message_actions",
        _group_event(),
    )


def test_ai_intent_visibility_requires_key_and_feature(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "get_shared_config",
        lambda: _config(ai_key="key", ai_intent_enabled=True),
    )
    monkeypatch.setattr(
        visibility,
        "is_event_feature_allowed",
        lambda _event, feature: feature == "ai_intent",
    )

    assert visibility.plugin_visible_for_event(
        "AI意图动作",
        "ironsbot.custom_plugins.ai_intent_actions",
        _group_event(),
    )
