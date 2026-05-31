from nonebot import get_driver, get_plugin_config
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    ai_chat_api_key: str = ""
    ai_chat_base_url: str = "https://api.deepseek.com"
    ai_chat_model: str = "deepseek-v4-flash"
    ai_chat_system_prompt: str = (
        "你是一个接入QQ群的聊天助手。"
        "回答要自然、简洁、友好。"
        "不知道就直说，不要编造。"
    )
    ai_chat_reset_commands: list[str] = Field(
        default_factory=lambda: ["清空聊天", "重置聊天", "清空上下文"]
    )
    ai_chat_allowed_group_ids: list[int] = Field(default_factory=list)
    ai_chat_allowed_user_ids: list[int] = Field(default_factory=list)
    ai_chat_admin_uids: list[int] = Field(default_factory=list)
    ai_chat_allow_group_owner: bool = True
    ai_chat_history_turns: int = Field(default=6, ge=0, le=20)
    ai_chat_timeout_seconds: float = Field(default=45.0, gt=0)
    ai_chat_max_tokens: int = Field(default=800, gt=0)
    ai_chat_temperature: float = Field(default=0.7, ge=0, le=2)
    ai_chat_thinking_enabled: bool = False
    ai_chat_send_waiting_notice: bool = True
    ai_chat_max_reply_chars: int = Field(default=1500, gt=0)

    @field_validator("ai_chat_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("ai_chat_reset_commands")
    @classmethod
    def normalize_commands(cls, value: list[str]) -> list[str]:
        commands = []
        for command in value:
            command = command.strip()
            if command and command not in commands:
                commands.append(command)
        return commands


plugin_config = get_plugin_config(Config)


def get_ai_chat_admin_uids() -> set[int]:
    uids = set(plugin_config.ai_chat_admin_uids)

    superusers = getattr(
        get_driver().config,
        "superusers",
        set(),
    )

    for uid in superusers:
        try:
            uids.add(int(uid))
        except (TypeError, ValueError):
            continue

    return uids
