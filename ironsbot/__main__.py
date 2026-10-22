# SPDX-License-Identifier: MIT
import sys
from io import TextIOWrapper

import uvicorn
from loguru import logger
from pydantic import ValidationError

from ironsbot.app.bootstrap import bootstrap
from ironsbot.config.loader import (
    ConfigFileNotFoundError,
    TOMLDecodeError,
)

CONFIG_LOAD_ERROR_EXIT_CODE = 2

if __name__ == "__main__" and isinstance(sys.stderr, TextIOWrapper):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

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
    uvicorn.run(
        application.asgi,
        host=application.settings.bot.host,
        port=application.settings.bot.port,
        log_level=logger.level(application.settings.bot.log_level).no,
        loop="asyncio",
        http="h11",
        ws="websockets-sansio",
    )
