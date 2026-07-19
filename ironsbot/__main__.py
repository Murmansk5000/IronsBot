# SPDX-License-Identifier: MIT
import sys

import nonebot

from ironsbot.app.bootstrap import bootstrap
from ironsbot.config.loader import ConfigFileNotFoundError

try:
    application = bootstrap()
except ConfigFileNotFoundError as error:
    if __name__ != "__main__":
        raise
    sys.stderr.write(f"{error}\n")
    raise SystemExit(2) from None

if __name__ == "__main__":
    nonebot.run(app=application.asgi)
