import subprocess
import sys

PURE_BILIBILI_SERVICE_MODULES = (
    "ironsbot.services.bilibili.menu",
)


def test_pure_bilibili_services_do_not_import_runtime_modules() -> None:
    script = """
import importlib
import sys

module_name = sys.argv[1]
importlib.import_module(module_name)
for forbidden in (
    "nonebot",
    "nonebot.log",
):
    if forbidden in sys.modules:
        raise SystemExit(f"{module_name} imported {forbidden}")
print(f"{module_name} import clean")
"""
    for module_name in PURE_BILIBILI_SERVICE_MODULES:
        result = subprocess.run(
            [sys.executable, "-c", script, module_name],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr or result.stdout
