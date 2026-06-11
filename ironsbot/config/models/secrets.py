# SPDX-License-Identifier: MIT
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SecretsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    onebot_access_token: str = ""
    ai_key: str = ""
    sendpic_cnb_token: str | None = None


class CredentialsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    headless_seer_user_id: int | None = Field(default=None, ge=10001)
    headless_seer_password: str | None = None


__all__ = ["CredentialsConfig", "SecretsConfig"]
