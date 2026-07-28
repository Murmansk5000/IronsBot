# SPDX-License-Identifier: MIT
"""Compatibility re-export for runtime code.

The semantic model belongs to :mod:`ironsbot.core` so services and optional
extensions can use it without depending on the NoneBot runtime layer.
"""

from ironsbot.core.semantic_requests import (  # noqa: F401
    ActionDefinition,
    SemanticRequest,
    SemanticRequestSource,
    SemanticTarget,
    current_semantic_request_trace,
    normalized_text_target,
    semantic_request_scope,
    singleton_target,
)
