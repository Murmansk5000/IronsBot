from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ironsbot.core.commands import (
    command_text_matches,
    normalize_command_text,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ironsbot.core.feature_policy import FeatureService
    from ironsbot.core.messaging import AiIntentAction
    from ironsbot.core.platform import ActorRef, ConversationRef


class TemplateContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def contains_any_keyword(text: str, keywords: list[str]) -> bool:
    normalized = normalize_command_text(text)
    return any(normalize_command_text(keyword) in normalized for keyword in keywords)


def excluded_by_command(
    text: str,
    action: AiIntentAction,
    team_resource_commands: Sequence[str],
) -> bool:
    exclude_commands = list(action.exclude_commands)
    if action.action == "team_resource":
        exclude_commands.extend(team_resource_commands)

    return bool(exclude_commands) and command_text_matches(text, exclude_commands)


def is_action_allowed(
    features: FeatureService,
    actor: ActorRef,
    conversation: ConversationRef,
    action: AiIntentAction,
) -> bool:
    return features.is_feature_allowed(actor, conversation, action.feature)


def is_ai_intent_allowed(
    features: FeatureService,
    actor: ActorRef,
    conversation: ConversationRef,
) -> bool:
    return features.is_feature_allowed(actor, conversation, "ai_intent")


def format_action_template(action: AiIntentAction, template: str, text: str) -> str:
    return template.format_map(
        TemplateContext(
            action_id=action.id or "unnamed",
            feature=action.feature,
            intent=action.intent,
            keywords=", ".join(action.keywords),
            message=text,
        )
    )


def build_intent_prompt(action: AiIntentAction, text: str) -> str:
    return format_action_template(action, action.classifier_prompt, text)


def reply_is_yes(reply: str) -> bool:
    normalized = reply.strip().lower()
    first_line = re.sub(
        r"^[\s.\u3002:\uff1a,\uff0c\"'`]+|"
        r"[\s.\u3002:\uff1a,\uff0c\"'`]+$",
        "",
        normalized.splitlines()[0],
    )
    return first_line in {
        "yes",
        "y",
        "true",
        "\u662f",
        "\u5bf9",
        "\u7b26\u5408",
    }
