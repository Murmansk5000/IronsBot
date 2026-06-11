# SPDX-License-Identifier: MIT
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ironsbot.config.models.activity import ActivityConfig
from ironsbot.config.models.ai import AiConfig
from ironsbot.config.models.bilibili import BilibiliConfig
from ironsbot.config.models.feature import FeatureConfig
from ironsbot.config.models.message import MessageConfig
from ironsbot.config.models.runtime import RuntimeConfig
from ironsbot.config.models.seer import SeerConfig


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature: FeatureConfig = Field(default_factory=FeatureConfig)
    ai: AiConfig = Field(default_factory=AiConfig)
    bilibili: BilibiliConfig = Field(default_factory=BilibiliConfig)
    activity: ActivityConfig = Field(default_factory=ActivityConfig)
    message: MessageConfig = Field(default_factory=MessageConfig)
    seer: SeerConfig = Field(default_factory=SeerConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)


__all__ = ["AppConfig"]
