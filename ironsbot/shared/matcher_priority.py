# SPDX-License-Identifier: MIT
from ironsbot.config import get_app_config


def get_matcher_priority(name: str, fallback: int) -> int:
    priorities = get_app_config().runtime.matcher_priority
    value = getattr(priorities, name, fallback)
    return int(value)


__all__ = ["get_matcher_priority"]
