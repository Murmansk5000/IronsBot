# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot import get_plugin_config
from pydantic import BaseModel, Field, field_validator

from ironsbot.custom_plugins.common.config_utils import nested_json_config
from ironsbot.custom_plugins.common.render_config import RenderConfig


class Config(BaseModel):
    render_config: RenderConfig = Field(default_factory=RenderConfig)

    @field_validator("render_config", mode="before")
    @classmethod
    def normalize_render_config(cls, value: object) -> object:
        return nested_json_config(value, RenderConfig, name="RENDER_CONFIG")


plugin_config = get_plugin_config(Config)
