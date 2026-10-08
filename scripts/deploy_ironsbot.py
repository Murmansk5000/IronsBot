# SPDX-License-Identifier: MIT
"""CLI entrypoint; share the application's supervised deployment path."""

import asyncio

from ironsbot.integrations.docker.deployment_launch import main

if __name__ == "__main__":
    asyncio.run(main())
