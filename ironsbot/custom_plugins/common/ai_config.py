from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

from .config_utils import (
    int_list,
    json_array,
    json_object,
    nested_json_config,
    string_list,
)

KEYWORDS_REQUIRED_ERROR = "enabled AI action must configure keywords"
MESSAGE_REQUIRED_ERROR = "message AI action must configure message"
AI_REPLY_PROMPT_REQUIRED_ERROR = "ai_reply AI action must configure reply_prompt"

DEFAULT_PROMPT = (
    "你是 IronsBot，一个接入 QQ 群的赛尔号信息查询机器人。"
    "回答应简洁、友好、诚实；无法确认时直接说明不确定，不要编造。"
)

DEFAULT_JOIN_TEAM_INTENT = (
    "Judge whether the QQ group message means the sender wants to join, apply for, "
    "or find a Seer team/guild. Answer yes only when the sender is asking to join "
    "a team, asking whether they can enter the team, or asking for the team info "
    "for joining. Answer no when the message only queries team data, discusses "
    "team resources, asks someone to buy resources, or casually mentions teams."
)

DEFAULT_CLASSIFIER_PROMPT = (
    "You are a strict intent classifier for a QQ bot.\n"
    "Only output one word: yes or no.\n"
    "Intent definition: {intent}\n"
    "Message: {message}\n"
    "Does the message match the intent?"
)

DEFAULT_KEYWORD_INFO_PROMPT = (
    "You are IronsBot, a concise QQ group assistant.\n"
    "Matched action: {action_id}\n"
    "Keywords: {keywords}\n"
    "User message: {message}\n"
    "Reply briefly and directly. If real-time bot data is needed, say which bot "
    "command or feature should be used instead of inventing data."
)


class AiActionBase(BaseModel):
    id: str = ""
    enabled: bool = True
    template: str = ""
    feature: str = "ai_intent"
    keywords: list[str] = Field(default_factory=list)
    intent: str = DEFAULT_JOIN_TEAM_INTENT
    classifier_prompt: str = DEFAULT_CLASSIFIER_PROMPT
    action: Literal["message", "team_shortcut", "ai_reply"] = "team_shortcut"
    message: str = ""
    reply_prompt: str = ""
    team_ids: list[int] = Field(default_factory=list)
    include_team_resource_notice: bool = False
    exclude_commands: list[str] = Field(default_factory=list)

    @field_validator("keywords", "exclude_commands", mode="before")
    @classmethod
    def normalize_string_list(cls, value: object) -> object:
        return string_list(value)

    @field_validator("team_ids", mode="before")
    @classmethod
    def normalize_int_list(cls, value: object) -> object:
        return int_list(value)

    @field_validator("feature")
    @classmethod
    def normalize_feature(cls, value: str) -> str:
        feature = value.strip()
        return feature or "ai_intent"


class AiActionTemplate(AiActionBase):
    pass


class AiIntentAction(AiActionBase):
    @model_validator(mode="after")
    def validate_enabled_action(self) -> Self:
        if not self.enabled:
            return self

        if not self.keywords and not self.template:
            raise ValueError(KEYWORDS_REQUIRED_ERROR)

        if self.action == "message" and not self.message.strip():
            raise ValueError(MESSAGE_REQUIRED_ERROR)

        if self.action == "ai_reply" and not self.reply_prompt.strip():
            raise ValueError(AI_REPLY_PROMPT_REQUIRED_ERROR)

        return self


def _default_templates() -> dict[str, AiActionTemplate]:
    return {
        "join_team": AiActionTemplate(
            id="join_team",
            keywords=["战队"],
            action="team_shortcut",
            intent=DEFAULT_JOIN_TEAM_INTENT,
            include_team_resource_notice=False,
        ),
        "keyword_info": AiActionTemplate(
            id="keyword_info",
            action="ai_reply",
            intent=(
                "The message is asking for information or explanation about "
                "the configured keywords."
            ),
            reply_prompt=DEFAULT_KEYWORD_INFO_PROMPT,
        ),
    }


def _default_actions() -> list[AiIntentAction]:
    return [AiIntentAction(template="join_team")]


class AiConfig(BaseModel):
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-pro"
    prompt: str = DEFAULT_PROMPT
    reset_commands: list[str] = Field(
        default_factory=lambda: ["清空聊天", "重置聊天", "清空上下文"]
    )
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
    intent_actions_enabled: bool = True
    action_templates: dict[str, AiActionTemplate] = Field(
        default_factory=_default_templates
    )
    intent_actions: list[AiIntentAction] = Field(default_factory=_default_actions)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("reset_commands", mode="before")
    @classmethod
    def normalize_commands(cls, value: object) -> object:
        return string_list(value)

    @field_validator("action_templates", mode="before")
    @classmethod
    def normalize_templates(cls, value: object) -> object:
        if value is None or value == "":
            return _default_templates()

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return _default_templates()
            return json_object(text, name="AI_CONFIG.action_templates")

        return value

    @field_validator("intent_actions", mode="before")
    @classmethod
    def normalize_actions(cls, value: object) -> object:
        if value is None or value == "":
            return _default_actions()

        if isinstance(value, str):
            text = value.strip()
            if not text:
                return _default_actions()
            return json_array(text, name="AI_CONFIG.intent_actions")

        return value

    @model_validator(mode="after")
    def merge_default_templates(self) -> Self:
        templates = _default_templates()
        for template_id, template in self.action_templates.items():
            base = templates.get(template_id)
            if base is None:
                templates[template_id] = template
                continue

            merged = base.model_dump()
            merged.update(template.model_dump(exclude_unset=True))
            templates[template_id] = AiActionTemplate.model_validate(merged)

        self.action_templates = templates
        return self


class Config(BaseModel):
    ai_key: str = ""
    ai_config: AiConfig = Field(default_factory=AiConfig)

    @field_validator("ai_config", mode="before")
    @classmethod
    def normalize_ai_config(cls, value: object) -> object:
        return nested_json_config(value, AiConfig, name="AI_CONFIG")


def _merge_template(
    template: AiActionTemplate,
    action: AiIntentAction,
) -> dict[str, Any]:
    template_data = template.model_dump()
    action_data = action.model_dump(exclude_unset=True)
    template_data.update(action_data)
    return template_data


def resolve_configured_actions(config: AiConfig) -> list[AiIntentAction]:
    actions: list[AiIntentAction] = []
    for action in config.intent_actions:
        resolved_action = action
        if action.template:
            template = config.action_templates.get(action.template)
            if template is not None:
                resolved_action = AiIntentAction.model_validate(
                    _merge_template(template, action)
                )
        actions.append(resolved_action)
    return actions
