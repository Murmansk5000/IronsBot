from pathlib import Path

from pydantic import BaseModel, Field


class RenderConfig(BaseModel):
    cache_dir: Path | None = None
    cache_max_size_mb: int = Field(default=200, gt=0)
    clear_on_startup: bool = True
