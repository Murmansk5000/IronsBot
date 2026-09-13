# SPDX-License-Identifier: MIT
"""Errors raised by the OneBot prompt-session adapter."""


class PromptSessionManagerMissingError(RuntimeError):
    pass


class PromptLoopConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("queued prompt requires a reply check")
