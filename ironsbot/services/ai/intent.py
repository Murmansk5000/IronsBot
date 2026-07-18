import re
from collections.abc import Sequence

from nonebot.adapters.onebot.v11 import (
    GroupMessageEvent,
    MessageEvent,
)

from ironsbot.config.models.ai import (
    AiIntentAction,
)
from ironsbot.core.commands import (
    command_text_matches,
    normalize_command_text,
)
from ironsbot.core.features import FIRE_MANUAL_INTENT_FEATURE
from ironsbot.shared.features import (
    group_has_feature,
    is_group_feature_allowed,
    is_private_feature_allowed,
)

FIRE_MANUAL_ANNOUNCEMENT_MARKERS = (
    "发布",
    "已发布",
    "正式版",
    "上线",
    "更新",
    "新版",
    "分享",
    "推荐",
    "转发",
)
FIRE_MANUAL_LINK_MARKERS = (
    "http",
    "https",
    "seerinfo",
    "yuyuqaq",
    "firedict",
)
FIRE_MANUAL_REQUEST_MARKERS = (
    "在哪",
    "哪里",
    "哪儿",
    "入口",
    "地址",
    "链接",
    "网址",
    "求",
    "想要",
    "我要",
    "要个",
    "要一个",
    "给我",
    "发我",
    "发一下",
    "发个",
    "谁有",
    "来个",
    "下载",
)
FIRE_MANUAL_SUBJECT_MARKERS = ("火火手册", "手册")


class TemplateContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def contains_any_keyword(text: str, keywords: list[str]) -> bool:
    normalized = normalize_command_text(text)
    return any(
        normalize_command_text(keyword) in normalized
        for keyword in keywords
    )


def _contains_any_normalized(text: str, markers: tuple[str, ...]) -> bool:
    normalized = normalize_command_text(text)
    return any(normalize_command_text(marker) in normalized for marker in markers)


def is_fire_manual_announcement_or_share(text: str) -> bool:
    has_announcement = _contains_any_normalized(
        text,
        FIRE_MANUAL_ANNOUNCEMENT_MARKERS,
    )
    has_manual_link = _contains_any_normalized(text, FIRE_MANUAL_LINK_MARKERS)
    has_request = _contains_any_normalized(text, FIRE_MANUAL_REQUEST_MARKERS)

    if has_announcement and has_manual_link:
        return True

    if has_announcement and not has_request:
        return True

    return has_manual_link and not has_request


def has_fire_manual_strong_request(text: str) -> bool:
    return (
        _contains_any_normalized(text, FIRE_MANUAL_SUBJECT_MARKERS)
        and _contains_any_normalized(text, FIRE_MANUAL_REQUEST_MARKERS)
        and not is_fire_manual_announcement_or_share(text)
    )


def passes_action_prefilter(text: str, action: AiIntentAction) -> bool:
    if action.feature == FIRE_MANUAL_INTENT_FEATURE:
        return has_fire_manual_strong_request(text)
    return True


def excluded_by_command(
    text: str,
    action: AiIntentAction,
    team_resource_commands: Sequence[str],
) -> bool:
    exclude_commands = list(action.exclude_commands)
    if action.action == "team_resource":
        exclude_commands.extend(team_resource_commands)

    return bool(exclude_commands) and command_text_matches(text, exclude_commands)


def excluded_by_context(text: str, action: AiIntentAction) -> bool:
    if action.feature == FIRE_MANUAL_INTENT_FEATURE:
        return is_fire_manual_announcement_or_share(text)
    return False


def is_action_allowed(event: MessageEvent, action: AiIntentAction) -> bool:
    if isinstance(event, GroupMessageEvent):
        if action.feature == FIRE_MANUAL_INTENT_FEATURE:
            return group_has_feature(event.group_id, action.feature)
        return is_group_feature_allowed(
            event.user_id,
            event.group_id,
            action.feature,
        )

    return is_private_feature_allowed(event.user_id, action.feature)


def is_ai_intent_allowed(event: MessageEvent) -> bool:
    if isinstance(event, GroupMessageEvent):
        return is_group_feature_allowed(
            event.user_id,
            event.group_id,
            "ai_intent",
        )

    return is_private_feature_allowed(event.user_id, "ai_intent")


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
