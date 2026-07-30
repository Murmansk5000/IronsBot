# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import Any

from ironsbot.runtime.commands import CommandAccess, CommandDescriptor


def commands_from_rows(
    plugin_id: str,
    section: str,
    feature: str | None,
    rows: tuple[tuple[str, tuple[str, ...], str, dict[str, Any]], ...],
) -> tuple[CommandDescriptor, ...]:
    descriptors = []
    for command_id, examples, description, raw_options in rows:
        options = dict(raw_options)
        command_features = options.pop(
            "features_any",
            (feature,) if feature is not None else (),
        )
        access = options.pop("access", (CommandAccess(),))
        descriptors.append(
            CommandDescriptor(
                id=command_id,
                plugin_id=plugin_id,
                section=section,
                examples=examples,
                description=description,
                features_any=command_features,
                access=access,
                **options,
            )
        )
    return tuple(descriptors)
