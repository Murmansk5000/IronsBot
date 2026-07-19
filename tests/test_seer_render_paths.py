import os
import subprocess
import sys
from pathlib import Path

from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    PEAK_PET_RANK_TEMPLATE_PATH,
    PEAK_POOL_TEMPLATE_PATH,
    PEAK_POOL_VOTE_TEMPLATE_PATH,
    PET_INFO_IMAGES_PATH,
    SEER_ASSET_TEMPLATES_PATH,
    SHARED_TEMPLATE_PATH,
    TYPE_MATCHUP_TEMPLATE_PATH,
)

TEMPLATE_PATHS = (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    PEAK_PET_RANK_TEMPLATE_PATH,
    PEAK_POOL_TEMPLATE_PATH,
    PEAK_POOL_VOTE_TEMPLATE_PATH,
    TYPE_MATCHUP_TEMPLATE_PATH,
)

ACTIVE_RENDER_MODULES = (
    "ironsbot.services.seer.rendering.custom_pet_info",
    "ironsbot.services.seer.rendering.peak_pet_rank",
    "ironsbot.services.seer.rendering.peak_pool",
    "ironsbot.services.seer.rendering.peak_pool_vote",
    "ironsbot.services.seer.rendering.type_matchup",
)


def test_active_seer_template_paths_exist() -> None:
    assert SEER_ASSET_TEMPLATES_PATH.is_dir()
    assert SHARED_TEMPLATE_PATH.is_dir()

    for template_path in TEMPLATE_PATHS:
        assert template_path.is_dir()
        assert (template_path / "template.html.j2").is_file()


def test_active_seer_pet_gender_icon_paths_exist() -> None:
    assert PET_INFO_IMAGES_PATH.is_dir()

    for gender_id in ("0", "1", "2"):
        assert (PET_INFO_IMAGES_PATH / f"{gender_id}.png").is_file()


def test_active_seer_render_modules_import_after_bot_bootstrap() -> None:
    module_args = ", ".join(repr(module_name) for module_name in ACTIVE_RENDER_MODULES)
    script = f"""
import importlib
import ironsbot.__main__

for module_name in ({module_args},):
    importlib.import_module(module_name)
print("render import ok")
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "IRONSBOT_CONFIG": str(
                Path(__file__).resolve().parents[1] / "config.example.toml"
            ),
        },
    )

    assert result.returncode == 0, result.stderr
