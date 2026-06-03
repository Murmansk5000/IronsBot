from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    ai_chat_api_key: str = ""
    ai_chat_base_url: str = "https://api.deepseek.com"
    ai_chat_model: str = "deepseek-v4-flash"
    ai_chat_system_prompt: str = (
        "你是 IronsBot，一个接入 QQ 群的赛尔号信息查询机器人。"
        "你的主要定位是帮助群友查询和讨论赛尔号相关内容，例如精灵、技能、魂印、种族值、属性克制、巅峰环境、活动链接和机器人使用问题。"
        "你也可以自然地闲聊，但回答应保持简洁、友好、像群聊里的机器人助手。"
        "如果用户问到实时数据库查询、图片渲染、B站动态、会议回复、发图等机器人插件功能，你可以说明这些由 IronsBot 的插件处理。"
        "如果你无法确认事实，直接说明不确定，不要编造。"
    )
    ai_chat_reset_commands: list[str] = Field(
        default_factory=lambda: ["清空聊天", "重置聊天", "清空上下文"]
    )
    ai_chat_allowed_group_ids: list[int] = Field(default_factory=list)
    ai_chat_allowed_user_ids: list[int] = Field(default_factory=list)
    ai_chat_history_turns: int = Field(default=6, ge=0, le=20)
    ai_chat_timeout_seconds: float = Field(default=45.0, gt=0)
    ai_chat_max_tokens: int = Field(default=800, gt=0)
    ai_chat_temperature: float = Field(default=0.7, ge=0, le=2)
    ai_chat_thinking_enabled: bool = False
    ai_chat_send_waiting_notice: bool = False
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
