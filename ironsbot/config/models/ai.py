# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.core.commands import json_object
from ironsbot.core.features import FIRE_MANUAL_INTENT_FEATURE
from ironsbot.core.messaging import (
    DEFAULT_JOIN_TEAM_INTENT,
    DEFAULT_JOIN_TEAM_MESSAGES,
    FIRE_MANUAL_LINK_MESSAGE,
    AiIntentAction,
)

KEYWORDS_REQUIRED_ERROR = "enabled AI action must configure keywords"
MESSAGE_REQUIRED_ERROR = "message AI action must configure message"
TEAM_RECOMMEND_MESSAGES_REQUIRED_ERROR = (
    "team_recommend AI action must configure messages"
)
TEAM_RECOMMEND_LEGACY_MESSAGE_ERROR = (
    "team_recommend AI action uses messages instead of message"
)
AI_REPLY_PROMPT_REQUIRED_ERROR = "ai_reply AI action must configure reply_prompt"
UNKNOWN_AI_ACTION_ERROR = (
    "unknown AI intent action must configure a complete action definition"
)
DEFAULT_AI_PROMPT = (
    "你是 IronsBot，一个接入 QQ 群的赛尔号信息查询机器人。"
    "回答应简洁、友好、诚实；无法确认时直接说明不确定，不要编造。"
)
DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS = 600.0
DEFAULT_FIRE_MANUAL_INTENT = (
    "Judge whether the QQ group message explicitly asks for the Fire manual "
    "entry, link, address, URL, download, or where to read it. Answer yes only "
    "when the sender is requesting the manual link/入口/地址/下载. Answer no when "
    "the message only mentions 手册 or 火火手册, discusses manual content, cites the "
    "manual as a source, asks why it has not updated or cannot open, announces "
    "or shares a manual release/link, or is unrelated to asking for the link."
)
DEFAULT_KEYWORD_INFO_PROMPT = (
    "You are IronsBot, a concise QQ group assistant.\n"
    "Matched action: {action_id}\n"
    "Keywords: {keywords}\n"
    "User message: {message}\n"
    "Reply briefly and directly. If real-time bot data is needed, say which bot "
    "command or feature should be used instead of inventing data."
)


def builtin_ai_actions() -> dict[str, AiIntentAction]:
    return {
        "team_recommend": AiIntentAction(
            id="team_recommend",
            feature="ai_intent_team_recommend",
            keywords=["战队"],
            action="team_recommend",
            intent=DEFAULT_JOIN_TEAM_INTENT,
            messages=list(DEFAULT_JOIN_TEAM_MESSAGES),
            include_team_resource_notice=False,
        ),
        "keyword_info": AiIntentAction(
            id="keyword_info",
            action="ai_reply",
            intent=(
                "The message is asking for information or explanation about "
                "the configured keywords."
            ),
            reply_prompt=DEFAULT_KEYWORD_INFO_PROMPT,
        ),
        "fire_manual": AiIntentAction(
            id="fire_manual",
            feature=FIRE_MANUAL_INTENT_FEATURE,
            keywords=["手册"],
            action="message",
            intent=DEFAULT_FIRE_MANUAL_INTENT,
            message=FIRE_MANUAL_LINK_MESSAGE,
        ),
    }


def default_ai_actions() -> dict[str, AiIntentAction]:
    actions = builtin_ai_actions()
    return {
        "team_recommend": actions["team_recommend"],
        "fire_manual": actions["fire_manual"],
    }


class AiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(default="", exclude=True, repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    prompt: str = DEFAULT_AI_PROMPT
    history_turns: int = Field(default=6, ge=0, le=20)
    memory: bool = True
    memory_path: Path = Path("data/ai_chat/memory.sqlite")
    memory_turns: int = Field(default=8, ge=0, le=50)
    memory_max_chars: int = Field(default=1200, gt=0)
    timeout: float = Field(default=45.0, gt=0)
    max_tokens: int = Field(default=800, gt=0)
    temperature: float = Field(default=0.7, ge=0, le=2)
    thinking: bool = False
    waiting_notice: bool = False
    max_reply_chars: int = Field(default=1500, gt=0)
    admin_notice_cooldown_seconds: float = Field(
        default=DEFAULT_AI_ADMIN_NOTICE_COOLDOWN_SECONDS,
        ge=0,
    )
    intent_actions_enabled: bool = True
    intent_actions: dict[str, AiIntentAction] = Field(
        default_factory=default_ai_actions
    )

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("intent_actions", mode="before")
    @classmethod
    def normalize_actions(cls, value: object) -> object:
        if value is None or value == "":
            return default_ai_actions()

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return default_ai_actions()
            return json_object(text, name="ai.intent_actions")

        return value

    @model_validator(mode="after")
    def merge_default_actions(self) -> Self:
        self.intent_actions = _resolve_action_map(self.intent_actions)
        return self


def _merge_action(
    base_action: AiIntentAction,
    action: AiIntentAction,
) -> dict[str, Any]:
    merged_data = base_action.model_dump()
    action_data = action.model_dump(exclude_unset=True)
    merged_data.update(action_data)
    return merged_data


def _validate_resolved_action(action: AiIntentAction) -> None:
    if not action.enabled:
        return

    if not action.keywords:
        raise ValueError(  # noqa: TRY003
            f"ai.intent_actions.{action.id}: {KEYWORDS_REQUIRED_ERROR}"
        )

    if action.action == "message" and not action.message.strip():
        raise ValueError(  # noqa: TRY003
            f"ai.intent_actions.{action.id}: {MESSAGE_REQUIRED_ERROR}"
        )

    if action.action == "team_recommend" and not action.messages:
        raise ValueError(  # noqa: TRY003
            f"ai.intent_actions.{action.id}: "
            f"{TEAM_RECOMMEND_MESSAGES_REQUIRED_ERROR}"
        )

    if action.action == "ai_reply" and not action.reply_prompt.strip():
        raise ValueError(  # noqa: TRY003
            f"ai.intent_actions.{action.id}: {AI_REPLY_PROMPT_REQUIRED_ERROR}"
        )


def _validate_custom_action(action_id: str, action: AiIntentAction) -> None:
    if not action.enabled:
        return

    fields_set = action.model_fields_set
    if "keywords" not in fields_set or "action" not in fields_set:
        raise ValueError(  # noqa: TRY003
            f"ai.intent_actions.{action_id}: {UNKNOWN_AI_ACTION_ERROR}"
        )


def _validate_no_legacy_team_recommend_message(
    action_id: str,
    action: AiIntentAction,
) -> None:
    fields_set = action.model_fields_set
    is_team_recommend = (
        action_id == "team_recommend" and "action" not in fields_set
    ) or ("action" in fields_set and action.action == "team_recommend")
    if not is_team_recommend or "message" not in fields_set:
        return

    raise ValueError(  # noqa: TRY003
        f"ai.intent_actions.{action_id}: {TEAM_RECOMMEND_LEGACY_MESSAGE_ERROR}"
    )


def _resolve_action_map(
    configured_actions: dict[str, AiIntentAction],
) -> dict[str, AiIntentAction]:
    builtins = builtin_ai_actions()
    resolved = default_ai_actions()

    for raw_action_id, action in configured_actions.items():
        action_id = raw_action_id.strip()
        if not action_id:
            continue

        _validate_no_legacy_team_recommend_message(action_id, action)

        builtin_action = builtins.get(action_id)
        if builtin_action is None:
            _validate_custom_action(action_id, action)
            resolved_action = action.model_copy(update={"id": action_id})
        else:
            resolved_action = AiIntentAction.model_validate(
                _merge_action(builtin_action, action)
            )
            resolved_action.id = action_id

        _validate_resolved_action(resolved_action)
        resolved[action_id] = resolved_action

    return resolved
