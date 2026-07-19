# SPDX-License-Identifier: MIT
import nonebot

from ironsbot.app.bootstrap import bootstrap

application = bootstrap()

if __name__ == "__main__":
    nonebot.run(app=application.asgi)
