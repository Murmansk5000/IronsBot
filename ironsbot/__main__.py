# SPDX-License-Identifier: MIT
import nonebot

from ironsbot.app.bootstrap import bootstrap

application = bootstrap()

if __name__ == "__main__":
    # Prefer the pure-Python Uvicorn runtime. It avoids optional native event-loop
    # and protocol accelerators while diagnosing production ExitCode=139 crashes.
    nonebot.run(
        app=application.asgi,
        loop="asyncio",
        http="h11",
        ws="websockets-sansio",
    )
