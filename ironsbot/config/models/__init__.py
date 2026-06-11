# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

_EXPORTS = {
    "ActivityConfig": ("ironsbot.config.models.activity", "ActivityConfig"),
    "AiConfig": ("ironsbot.config.models.ai", "AiConfig"),
    "AppConfig": ("ironsbot.config.models.app", "AppConfig"),
    "BilibiliConfig": ("ironsbot.config.models.bilibili", "BilibiliConfig"),
    "CredentialsConfig": ("ironsbot.config.models.secrets", "CredentialsConfig"),
    "DeploymentConfig": ("ironsbot.config.models.deployment", "DeploymentConfig"),
    "FeatureConfig": ("ironsbot.config.models.feature", "FeatureConfig"),
    "MessageConfig": ("ironsbot.config.models.message", "MessageConfig"),
    "RuntimeConfig": ("ironsbot.config.models.runtime", "RuntimeConfig"),
    "SecretsConfig": ("ironsbot.config.models.secrets", "SecretsConfig"),
    "SeerConfig": ("ironsbot.config.models.seer", "SeerConfig"),
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(name)

    module_name, attr_name = _EXPORTS[name]
    module = __import__(module_name, fromlist=[attr_name])
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


__all__ = list(_EXPORTS)
