"""Own historical infrastructure plugins before tests import their modules."""

import nonebot


def pytest_configure():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    for module in ("ironsbot.plugins.db_sync", "ironsbot.plugins.http_client"):
        if nonebot.load_plugin(module) is None:
            raise RuntimeError("Historical test infrastructure failed to load: " + module)
