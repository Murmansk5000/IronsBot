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
    ai_intent_enabled: bool = True,
    team_subscriptions: list[object] | None = None,
    group_actions: list[Action] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        ai=SimpleNamespace(intent_actions_enabled=ai_intent_enabled),
        message=SimpleNamespace(
            group_commands=group_actions or [],
            group_schedules=[],
            private_commands=[],
            private_schedules=[],
        ),
        seer=SimpleNamespace(
            team_resource=SimpleNamespace(
                subscriptions=team_subscriptions or [],
            ),
        ),
    )


def test_always_visible_help_is_shown() -> None:
    assert visibility.plugin_visible_for_event(
        "帮助",
        "ironsbot.plugins.help",
        _group_event(),
    )


def test_feature_module_visibility_uses_feature_service(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "group_has_feature",
        lambda _event, feature: feature == "seer",
    )

    assert visibility.plugin_visible_for_event(
        "赛尔号查询",
        "ironsbot.plugins.seer.query",
        _group_event(),
    )
    assert not visibility.plugin_visible_for_event(
        "榜单",
        "ironsbot.plugins.seer.rank_help",
        _group_event(),
    )


def test_seer_query_visible_when_any_seer_subfeature_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "group_has_feature",
        lambda _event, feature: feature == "seer_pet",
    )

    assert visibility.plugin_visible_for_event(
        "赛尔号查询",
        "ironsbot.plugins.seer.query",
        _group_event(),
    )


def test_rank_help_visible_when_seer_rank_allowed(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "group_has_feature",
        lambda _event, feature: feature == "seer_rank",
    )

    assert visibility.plugin_visible_for_event(
        "榜单",
        "ironsbot.plugins.seer.rank_help",
        _group_event(),
    )


def test_messaging_visibility_reads_app_config(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "get_app_config",
        lambda: _config(group_actions=[Action(enabled=True, feature="text")]),
    )
    monkeypatch.setattr(
        visibility,
        "group_has_feature",
        lambda _group_id, feature: feature == "text",
    )

    assert visibility.plugin_visible_for_event(
        "文本发送",
        "ironsbot.plugins.messaging",
        _group_event(),
    )


def test_ai_intent_visibility_requires_key_and_feature(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "_ai_key_configured",
        lambda: True,
    )
    monkeypatch.setattr(
        visibility,
        "get_app_config",
        lambda: _config(ai_intent_enabled=True),
    )
    monkeypatch.setattr(
        visibility,
        "group_has_feature",
        lambda _event, feature: feature == "ai_intent",
    )

    assert visibility.plugin_visible_for_event(
        "AI意图分析",
        "ironsbot.plugins.ai_intent",
        _group_event(),
    )
    assert not visibility.plugin_visible_for_event(
        "战队推荐",
        "ironsbot.plugins.team_recommend",
        _group_event(),
    )
    assert not visibility.plugin_visible_for_event(
        "战队审核入群提示",
        "ironsbot.plugins.team_audit_welcome",
        _group_event(),
    )


def test_team_resource_visibility_reads_app_config(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        visibility,
        "get_app_config",
        lambda: _config(team_subscriptions=[object()]),
    )
    monkeypatch.setattr(
        visibility,
        "group_has_feature",
        lambda _group_id, feature: feature == "team_resource_subscription",
    )

    assert visibility.plugin_visible_for_event(
        "战队资源订阅",
        "ironsbot.plugins.team_shortcut",
        _group_event(),
    )
