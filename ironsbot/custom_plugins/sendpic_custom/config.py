from pathlib import Path
from typing import Literal, TypeAlias

from nonebot import get_plugin_config, require
from pydantic import BaseModel, Field, field_validator, model_validator
from typing_extensions import Self

require("nonebot_plugin_localstore")

from nonebot_plugin_localstore import get_data_dir

BackendType: TypeAlias = Literal["cnb", "local"]

DEFAULT_MESSAGE_TEMPLATE = "{image}"


class PicConfig(BaseModel):
    id: str
    backend: BackendType
    command: str
    aliases: set[str] = Field(default_factory=set)
    image_dir: str
    image_filename_template: str
    help_message: str | None = None
    message_template: str = DEFAULT_MESSAGE_TEMPLATE


class Config(BaseModel):
    sendpic_cnb_token: str | None = None
    sendpic_cnb_repo: str | None = None
    sendpic_local_root: Path = get_data_dir("sendpic")
    sendpic_configs: list[PicConfig] = Field(default_factory=list)
    sendpic_enabled_ids: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("sendpic_configs")
    @classmethod
    def validate_pics(cls, v: list[PicConfig]) -> list[PicConfig]:
        seen: set[str] = set()
        for pic in v:
            if pic.id in seen:
                raise ValueError(f"图片类型【{pic.id}】重复")
            seen.add(pic.id)

        return v

    @model_validator(mode="after")
    def validate_configs(self) -> Self:
        for pic in self.sendpic_configs:
            if pic.backend == "cnb" and (
                not self.sendpic_cnb_token or not self.sendpic_cnb_repo
            ):
                raise ValueError(
                    f"CNB 相关配置未设置，而命令【{pic.command}】需要该配置"
                )
        return self


plugin_config = get_plugin_config(Config)


def pic_id_is_enabled(_id: str) -> bool:
    return _id in plugin_config.sendpic_enabled_ids


def filter_enabled_configs() -> list[PicConfig]:
    return [
        config
        for config in plugin_config.sendpic_configs
        if pic_id_is_enabled(config.id)
    ]
