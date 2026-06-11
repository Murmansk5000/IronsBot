from ironsbot.config.models.ai import AiIntentAction
from ironsbot.services.ai import intent


def test_intent_reply_yes_parser_accepts_short_yes_forms() -> None:
    assert intent.reply_is_yes(" yes.")
    assert intent.reply_is_yes("是")
    assert intent.reply_is_yes("符合\nreason")
    assert not intent.reply_is_yes("no")


def test_intent_template_preserves_unknown_fields() -> None:
    action = AiIntentAction(
        id="unit",
        keywords=["战队"],
        action="message",
        message="ok",
        intent="join",
    )

    assert (
        intent.format_action_template(
            action,
            "{action_id}:{feature}:{intent}:{keywords}:{message}:{missing}",
            "我要加战队",
        )
        == "unit:ai_intent:join:战队:我要加战队:{missing}"
    )


def test_intent_keyword_match_normalizes_text() -> None:
    assert intent.contains_any_keyword("我要 加 战队", ["加战队"])
