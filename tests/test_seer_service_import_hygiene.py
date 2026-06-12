import subprocess
import sys

PURE_SEER_SERVICE_MODULES = (
    "ironsbot.services.seer.autocard",
    "ironsbot.services.seer.countermark_stat_rank",
    "ironsbot.services.seer.player_formatting",
    "ironsbot.services.seer.player_query",
    "ironsbot.services.seer.rank_list",
    "ironsbot.services.seer.rank_usage",
    "ironsbot.services.seer.team",
    "ironsbot.services.seer.weekly_preview",
)


def test_pure_seer_services_do_not_import_runtime_modules() -> None:
    script = """
import importlib
import sys

module_name = sys.argv[1]
importlib.import_module(module_name)
for forbidden in (
    "nonebot",
    "nonebot.log",
    "ironsbot.services.seer.rank",
    "ironsbot.services.seer.rank_page_cache",
):
    if forbidden in sys.modules:
        raise SystemExit(f"{module_name} imported {forbidden}")
print(f"{module_name} import clean")
"""
    for module_name in PURE_SEER_SERVICE_MODULES:
        result = subprocess.run(
            [sys.executable, "-c", script, module_name],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
