import re

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
)

from ironsbot.config import get_app_config
from ironsbot.config.models.ai import (
    AiConfig,
    AiIntentAction,
    resolve_configured_actions,
)
from ironsbot.config.models.seer import TeamShortcutConfig
from ironsbot.shared.features import (
    is_group_feature_allowed,
    is_private_feature_allowed,
)
from ironsbot.shared.messaging.text import command_text_matches, normalize_command_text


class TemplateContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def get_ai_intent_config() -> AiConfig:
    return get_app_config().ai


def get_team_shortcut_config() -> TeamShortcutConfig:
    return get_app_config().seer.team_shortcut


def get_configured_actions() -> list[AiIntentAction]:
    return resolve_configured_actions(get_ai_intent_config())


def get_team_ids() -> list[int]:
    return get_team_shortcut_config().team_ids


def get_team_resource_users() -> list[int]:
    return get_team_shortcut_config().resource_users


def contains_any_keyword(text: str, keywords: list[str]) -> bool:
    normalized = normalize_command_text(text)
    return any(
        normalize_command_text(keyword) in normalized
        for keyword in keywords
    )


def excluded_by_command(text: str, action: AiIntentAction) -> bool:
    exclude_commands = list(action.exclude_commands)
    if action.action == "team_shortcut":
        exclude_commands.extend(get_team_shortcut_config().commands)

    return bool(exclude_commands) and command_text_matches(text, exclude_commands)


def is_action_allowed(event: MessageEvent, action: AiIntentAction) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_feature_allowed(
            event.user_id,
            event.group_id,
            action.feature,
        )

    return is_private_feature_allowed(event.user_id, action.feature)


def format_action_template(action: AiIntentAction, template: str, text: str) -> str:
    return template.format_map(
        TemplateContext(
            action_id=action.id or action.template or "unnamed",
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
