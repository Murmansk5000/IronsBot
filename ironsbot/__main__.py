# SPDX-License-Identifier: MIT
import sys

import nonebot
from pydantic import ValidationError

from ironsbot.app.bootstrap import bootstrap
from ironsbot.config.loader import (
    ConfigFileNotFoundError,
    TOMLDecodeError,
)

CONFIG_LOAD_ERROR_EXIT_CODE = 2

try:
    application = bootstrap()
except ConfigFileNotFoundError as error:
    if __name__ != "__main__":
        raise
    sys.stderr.write(f"{error}\n")
    raise SystemExit(CONFIG_LOAD_ERROR_EXIT_CODE) from None
except (TOMLDecodeError, ValidationError, TypeError, ValueError) as error:
    if __name__ != "__main__":
        raise
    sys.stderr.write(f"IronsBot 配置文件格式或字段错误：{error}\n")
    raise SystemExit(CONFIG_LOAD_ERROR_EXIT_CODE) from None

if __name__ == "__main__":
    # Prefer the pure-Python Uvicorn runtime. It avoids optional native event-loop
    # and protocol accelerators while diagnosing production ExitCode=139 crashes.
    nonebot.run(
        app=application.asgi,
        loop="asyncio",
        http="h11",
        ws="websockets-sansio",
    )
