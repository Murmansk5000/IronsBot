# SPDX-License-Identifier: MIT
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from typing_extensions import Self

from ironsbot.core.commands import (
    NormalizedIntList,
    NormalizedStringList,
    NormalizedStringSet,
)

DEFAULT_CLASSIFIER_PROMPT = (
    "You are a strict intent classifier for a chat bot.\n"
    "Only output one word: yes or no.\n"
    "Intent definition: {intent}\n"
    "Message: {message}\n"
    "Does the message match the intent?"
)


class AiIntentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    enabled: bool = True
    feature: str = "ai_intent"
    keywords: NormalizedStringList = Field(default_factory=list)
    intent: str = ""
    classifier_prompt: str = DEFAULT_CLASSIFIER_PROMPT
    action: Literal[
        "message",
        "promotion",
        "team_recommend",
        "team_resource",
        "ai_reply",
    ] = "message"
    message: str = ""
    messages: NormalizedStringList = Field(default_factory=list)
    promotion: str = ""
    reply_prompt: str = ""
    team_ids: NormalizedIntList = Field(default_factory=list)
    include_team_resource_notice: bool = False
    exclude_commands: NormalizedStringList = Field(default_factory=list)

    @field_validator("feature")
    @classmethod
    def normalize_feature(cls, value: str) -> str:
        return value.strip() or "ai_intent"


class PicConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    id: str
    enabled: bool = True
    backend: Literal["cnb", "local"]
    command: str
    aliases: NormalizedStringSet = Field(default_factory=set)
    mode: Literal["single", "indexed"]
    image_file: str | None = None
    image_dir: str | None = None
    image_filename_template: str | None = None
    message_template: str = "{image}"

    @model_validator(mode="after")
    def validate_image_source(self) -> Self:
        if self.mode == "single" and not self.image_file:
            raise ValueError("single 图片命令必须配置 image_file")  # noqa: TRY003
        if self.mode == "indexed" and (
            not self.image_dir or not self.image_filename_template
        ):
            raise ValueError(  # noqa: TRY003
                "indexed 图片命令必须配置 image_dir 和 image_filename_template"
            )
        return self


class SendpicBehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cnb_token: str | None = Field(default=None, exclude=True, repr=False)
    cnb_repo: str | None = None
    local_root: Path = Path("sendpic")
    configs: list[PicConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> Self:
        seen_ids: set[str] = set()
        for config in self.configs:
            if config.id in seen_ids:
                raise ValueError("图片命令 ID 重复：" + config.id)
            seen_ids.add(config.id)
        return self
