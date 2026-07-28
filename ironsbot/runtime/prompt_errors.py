# SPDX-License-Identifier: MIT
"""Prompt-session exceptions shared by runtime entry points."""


class PromptSessionManagerMissingError(RuntimeError):
    pass


class PromptLoopConfigurationError(ValueError):
    def __init__(self) -> None:
        super().__init__("queued prompt requires a reply check")
