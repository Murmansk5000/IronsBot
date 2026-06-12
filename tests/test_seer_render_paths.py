import subprocess
import sys

from ironsbot.services.seer.render_paths import (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    UPSTREAM_PEAK_PET_RANK_TEMPLATE_PATH,
    UPSTREAM_PEAK_POOL_TEMPLATE_PATH,
    UPSTREAM_PEAK_POOL_VOTE_TEMPLATE_PATH,
    UPSTREAM_PET_INFO_IMAGES_PATH,
    UPSTREAM_PET_INFO_TEMPLATE_PATH,
    UPSTREAM_SEER_INFO_TEMPLATES_PATH,
    UPSTREAM_SHARED_TEMPLATE_PATH,
    UPSTREAM_TYPE_MATCHUP_TEMPLATE_PATH,
)

TEMPLATE_PATHS = (
    CUSTOM_PET_INFO_TEMPLATE_PATH,
    UPSTREAM_PEAK_PET_RANK_TEMPLATE_PATH,
    UPSTREAM_PEAK_POOL_TEMPLATE_PATH,
    UPSTREAM_PEAK_POOL_VOTE_TEMPLATE_PATH,
    UPSTREAM_PET_INFO_TEMPLATE_PATH,
    UPSTREAM_TYPE_MATCHUP_TEMPLATE_PATH,
)

ACTIVE_RENDER_MODULES = (
    "ironsbot.services.seer.rendering.custom_pet_info",
    "ironsbot.services.seer.rendering.peak_pet_rank",
    "ironsbot.services.seer.rendering.peak_pool",
    "ironsbot.services.seer.rendering.peak_pool_vote",
    "ironsbot.services.seer.rendering.type_matchup",
    "ironsbot.services.seer.rendering.upstream_pet_info",
)


def test_active_seer_template_paths_exist() -> None:
    assert UPSTREAM_SEER_INFO_TEMPLATES_PATH.is_dir()
    assert UPSTREAM_SHARED_TEMPLATE_PATH.is_dir()

    for template_path in TEMPLATE_PATHS:
        assert template_path.is_dir()
        assert (template_path / "template.html.j2").is_file()


def test_active_seer_pet_gender_icon_paths_exist() -> None:
    assert UPSTREAM_PET_INFO_IMAGES_PATH.is_dir()

    for gender_id in ("0", "1", "2"):
        assert (UPSTREAM_PET_INFO_IMAGES_PATH / f"{gender_id}.png").is_file()


def test_active_seer_render_modules_import_after_bot_bootstrap() -> None:
    module_args = ", ".join(repr(module_name) for module_name in ACTIVE_RENDER_MODULES)
    script = f"""
import importlib
import bot

for module_name in ({module_args},):
    importlib.import_module(module_name)
print("render import ok")
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
