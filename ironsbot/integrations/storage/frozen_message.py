# SPDX-License-Identifier: MIT
"""Content-addressed outbound snapshots, excluding live prompt sessions."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from ironsbot.core.outbound import (
    BinaryImagePart,
    MentionPart,
    OutboundMessage,
    RemoteImagePart,
    TextPart,
)
from ironsbot.core.platform import ActorRef, Platform
from ironsbot.integrations.storage.bilibili_media_manifest import (
    decode_media,
    encode_media,
)

if TYPE_CHECKING:
    from pathlib import Path


def freeze_message(message: OutboundMessage, root: Path) -> str:
    entries = []
    for part in message.parts:
        if isinstance(part, TextPart):
            entries.append({"text": part.text})
        elif isinstance(part, MentionPart):
            entries.append({"actor": asdict(part.actor)})
        elif isinstance(part, (BinaryImagePart, RemoteImagePart)):
            entries.append({"media": encode_media(OutboundMessage((part,)), root)})
    return json.dumps(entries, ensure_ascii=False)


def thaw_message(payload: str, root: Path) -> OutboundMessage:
    parts = []
    for entry in json.loads(payload):
        if "text" in entry:
            parts.append(TextPart(entry["text"]))
        elif "actor" in entry:
            actor = entry["actor"]
            actor["platform"] = Platform(actor["platform"])
            parts.append(MentionPart(ActorRef(**actor)))
        else:
            media = decode_media(entry["media"], root)
            if media is None:
                raise ValueError("Frozen message contains empty media")  # noqa: TRY003
            parts.extend(media.parts)
    return OutboundMessage(tuple(parts))
