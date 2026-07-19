# SPDX-License-Identifier: MIT
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict


class PetConfigConfig(BaseModel):
    """Configuration for locally maintained pet build images."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    image_dir: Path = Path("data/pet_configs")
