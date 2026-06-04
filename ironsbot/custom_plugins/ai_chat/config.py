from pathlib import Path

from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator


class Config(BaseModel):
    ai_key: str = ""
    ai_base_url: str = "https://api.deepseek.com"
    ai_model: str = "deepseek-v4-flash"
    ai_prompt: str = (
        "你是 IronsBot，一个接入 QQ 群的赛尔号信息查询机器人。"
        "你的主要定位是帮助群友查询和讨论赛尔号相关内容，例如精灵、技能、魂印、种族值、属性克制、巅峰环境、活动链接和机器人使用问题。"
        "你也可以自然地闲聊，但回答应保持简洁、友好、像群聊里的机器人助手。"
        "如果用户问到实时数据库查询、图片渲染、B站动态、会议回复、发图等机器人插件功能，"
        "你可以说明这些由 IronsBot 的插件处理。"
        "如果你无法确认事实，直接说明不确定，不要编造。"
    )
    ai_reset_commands: list[str] = Field(
        default_factory=lambda: ["清空聊天", "重置聊天", "清空上下文"]
    )
    ai_groups: list[int] = Field(default_factory=list)
    ai_users: list[int] = Field(default_factory=list)
    ai_history_turns: int = Field(default=6, ge=0, le=20)
    ai_memory: bool = True
    ai_memory_path: Path = Path("data/ai_chat/memory.sqlite")
    ai_memory_turns: int = Field(default=8, ge=0, le=50)
    ai_memory_max_chars: int = Field(default=1200, gt=0)
    ai_timeout: float = Field(default=45.0, gt=0)
    ai_max_tokens: int = Field(default=800, gt=0)
    ai_temperature: float = Field(default=0.7, ge=0, le=2)
    ai_thinking: bool = False
    ai_waiting_notice: bool = False
    ai_max_reply_chars: int = Field(default=1500, gt=0)

    @field_validator("ai_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")

    @field_validator("ai_reset_commands")
    @classmethod
    def normalize_commands(cls, value: list[str]) -> list[str]:
        commands = []
        for raw_command in value:
            command = raw_command.strip()
            if command and command not in commands:
                commands.append(command)
        return commands


plugin_config = get_plugin_config(Config)
