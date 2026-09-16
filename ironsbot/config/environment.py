# SPDX-License-Identifier: MIT
"""Load local deployment variables before strict application configuration."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import dotenv_values

if TYPE_CHECKING:
    from collections.abc import MutableMapping

DEFAULT_ENVIRONMENT = "prod"


def load_runtime_environment(
    *,
    directory: Path | None = None,
    env: MutableMapping[str, str] | None = None,
) -> tuple[Path, ...]:
    """Load local dotenv files without overriding process/container variables."""

    values = os.environ if env is None else env
    root = Path.cwd() if directory is None else directory
    process_keys = set(values)
    base_path = root / ".env"
    base_values = _read_dotenv(base_path)
    environment = values.get("ENVIRONMENT") or base_values.get("ENVIRONMENT")
    environment = str(environment or DEFAULT_ENVIRONMENT).strip() or DEFAULT_ENVIRONMENT
    scoped_path = root / f".env.{environment}"
    scoped_values = _read_dotenv(scoped_path)

    merged = {**base_values, **scoped_values}
    for key, value in merged.items():
        if key not in process_keys and value is not None:
            values[key] = value

    return tuple(path for path in (base_path, scoped_path) if path.is_file())


def _read_dotenv(path: Path) -> dict[str, str | None]:
    if not path.is_file():
        return {}
    return dict(dotenv_values(path))
