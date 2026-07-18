# SPDX-License-Identifier: GPL-3.0-or-later
from ironsbot.runtime.matchers import MatcherRegistry
from ironsbot.services.seer.resources import SeerQueryResources

from .commands import install as install_commands
from .group import SeerMatcherGroup


def install(
    registry: MatcherRegistry,
    resources: SeerQueryResources,
) -> None:
    install_commands(
        SeerMatcherGroup(
            registry,
            resources,
        )
    )
