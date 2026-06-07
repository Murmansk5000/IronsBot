import json
from typing import Literal

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

KEYWORDS_REQUIRED_ERROR = "enabled AI intent action must configure keywords"
MESSAGE_REQUIRED_ERROR = "message AI intent action must configure message"


DEFAULT_JOIN_TEAM_INTENT = (
    "Judge whether the QQ group message means the sender wants to join, apply for, "
    "or find a Seer team/guild. Answer yes only when the sender is asking to join "
    "a team, asking whether they can enter the team, or asking for the team info "
    "for joining. Answer no when the message only queries team data, discusses "
    "team resources, asks someone to buy resources, or casually mentions teams."
)


class AiIntentAction(BaseModel):
    id: str = ""
    enabled: bool = True
    keywords: list[str] = Field(default_factory=list)
    group_ids: list[int] = Field(default_factory=list)
    user_ids: list[int] = Field(default_factory=list)
    intent: str = DEFAULT_JOIN_TEAM_INTENT
    action: Literal["message", "team_shortcut"] = "team_shortcut"
    message: str = ""
    team_ids: list[int] = Field(default_factory=list)
    include_team_resource_notice: bool = False
    exclude_commands: list[str] = Field(default_factory=list)

    @field_validator(
        "keywords",
        "exclude_commands",
        mode="before",
    )
    @classmethod
    def normalize_string_list(cls, value: object) -> object:
        if value is None or value == "":
            return []

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []

            if text.startswith("["):
                return json.loads(text)

            return [
                item.strip()
                for item in text.split(",")
                if item.strip()
            ]

        return value

    @field_validator("group_ids", "user_ids", "team_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        if value is None or value == "":
            return []

        if isinstance(value, int):
            return [value]

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []

            if text.startswith("["):
                return json.loads(text)

            return [
                int(item.strip())
                for item in text.split(",")
                if item.strip()
            ]

        return value

    @field_validator("keywords", "exclude_commands")
    @classmethod
    def dedupe_strings(cls, value: list[str]) -> list[str]:
        items: list[str] = []
        for raw_item in value:
            item = raw_item.strip()
            if item and item not in items:
                items.append(item)
        return items

    @model_validator(mode="after")
    def validate_enabled_action(self) -> Self:
        if not self.enabled:
            return self

        if not self.keywords:
            raise ValueError(KEYWORDS_REQUIRED_ERROR)

        if self.action == "message" and not self.message.strip():
            raise ValueError(MESSAGE_REQUIRED_ERROR)

        return self


def _default_actions() -> list[AiIntentAction]:
    return [
        AiIntentAction(
            id="join_team",
            keywords=["战队"],
            action="team_shortcut",
            intent=DEFAULT_JOIN_TEAM_INTENT,
            include_team_resource_notice=False,
        )
    ]


class Config(BaseModel):
    ai_intent_actions_enabled: bool = True
    ai_intent_actions: list[AiIntentAction] = Field(default_factory=_default_actions)

    @field_validator("ai_intent_actions", mode="before")
    @classmethod
    def normalize_actions(cls, value: object) -> object:
        if value is None or value == "":
            return _default_actions()

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return _default_actions()

            if text.startswith("["):
                return json.loads(text)

        return value


plugin_config = get_plugin_config(Config)
