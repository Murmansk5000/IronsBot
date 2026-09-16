from __future__ import annotations

from typing import TYPE_CHECKING

from ironsbot.config.environment import load_runtime_environment

if TYPE_CHECKING:
    from pathlib import Path


def test_runtime_environment_uses_scoped_file_over_base(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "ENVIRONMENT=dev\nSHARED=base\nBASE_ONLY=base\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.dev").write_text(
        "SHARED=scoped\nSCOPED_ONLY=scoped\n",
        encoding="utf-8",
    )
    env: dict[str, str] = {}

    loaded = load_runtime_environment(directory=tmp_path, env=env)

    assert loaded == (tmp_path / ".env", tmp_path / ".env.dev")
    assert env == {
        "ENVIRONMENT": "dev",
        "SHARED": "scoped",
        "BASE_ONLY": "base",
        "SCOPED_ONLY": "scoped",
    }


def test_runtime_environment_preserves_process_values(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "ENVIRONMENT=prod\nSECRET=base\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.dev").write_text(
        "SECRET=scoped\nLOCAL_ONLY=local\n",
        encoding="utf-8",
    )
    env = {"ENVIRONMENT": "dev", "SECRET": "process"}

    load_runtime_environment(directory=tmp_path, env=env)

    assert env == {
        "ENVIRONMENT": "dev",
        "SECRET": "process",
        "LOCAL_ONLY": "local",
    }


def test_runtime_environment_defaults_to_prod_scope(tmp_path: Path) -> None:
    (tmp_path / ".env.prod").write_text("PRODUCTION=yes\n", encoding="utf-8")
    env: dict[str, str] = {}

    loaded = load_runtime_environment(directory=tmp_path, env=env)

    assert loaded == (tmp_path / ".env.prod",)
    assert env == {"PRODUCTION": "yes"}
