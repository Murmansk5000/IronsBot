# SPDX-License-Identifier: MIT
from collections.abc import Mapping
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
    backend: Literal["builtin", "cnb", "local"]
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


def default_sendpic_configs() -> list[PicConfig]:
    """Return packaged single-image commands as normal image command configs."""

    return [
        PicConfig(
            id="study-table",
            backend="builtin",
            command="学习力",
            aliases={"学习力表", "学习力表格"},
            mode="single",
            image_file="学习力表格.png",
        ),
        PicConfig(
            id="peak-guide",
            backend="builtin",
            command="巅峰姬",
            mode="single",
            image_file="巅峰姬.png",
        ),
        PicConfig(
            id="initiative",
            backend="builtin",
            command="必先",
            mode="single",
            image_file="必先.png",
        ),
        PicConfig(
            id="skill-stone",
            backend="builtin",
            command="技能石",
            mode="single",
            image_file="技能石.png",
        ),
        PicConfig(
            id="anniversary-random-table",
            backend="builtin",
            command="周年庆伪随机表",
            aliases={"伪随机表"},
            mode="single",
            image_file="周年庆伪随机表.png",
        ),
    ]


class SendpicBehaviorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cnb_token: str | None = Field(default=None, exclude=True, repr=False)
    cnb_repo: str | None = None
    local_root: Path = Path("sendpic")
    configs: list[PicConfig] = Field(default_factory=default_sendpic_configs)

    @model_validator(mode="before")
    @classmethod
    def merge_packaged_commands(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        raw_configs = value.get("configs")
        if raw_configs is None or not isinstance(raw_configs, list):
            return value

        defaults = {
            config.id: config.model_dump(mode="json")
            for config in default_sendpic_configs()
        }
        extra_configs: list[object] = []
        seen_ids: set[str] = set()
        for raw_config in raw_configs:
            if not isinstance(raw_config, Mapping):
                return value
            raw_id = str(raw_config.get("id", "")).strip()
            if raw_id in seen_ids:
                raise ValueError("图片命令 ID 重复：" + raw_id)
            seen_ids.add(raw_id)
            if raw_id in defaults:
                defaults[raw_id].update(raw_config)
            else:
                extra_configs.append(raw_config)

        return {**value, "configs": [*defaults.values(), *extra_configs]}
