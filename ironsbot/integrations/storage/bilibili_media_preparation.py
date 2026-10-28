# SPDX-License-Identifier: MIT
"""Durable media preparation budgets and content-addressed source references."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ironsbot.core.outbound import BinaryImagePart, OutboundMessage
from ironsbot.integrations.storage.bilibili_delivery_lifecycle import (
    DeliveryLifecycleStore,
)
from ironsbot.integrations.storage.bilibili_media_manifest import (
    decode_media,
    encode_media,
)

if TYPE_CHECKING:
    from pathlib import Path

_MAX_ATTEMPTS = 4


def _reasons(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [reason for reason in value if isinstance(reason, str)]


class MediaPreparationStore(DeliveryLifecycleStore):
    media_root: Path

    def begin_media_preparation(
        self, dynamic_id: str, fingerprint: str
    ) -> tuple[int, float]:
        now = self._now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO media_preparations "
                "VALUES (?,?,?,?,0,'pending','{}')",
                (dynamic_id, fingerprint, now, now + 60),
            )
            stored, deadline, attempts, status = db.execute(
                "SELECT fingerprint,deadline,attempts,status FROM media_preparations "
                "WHERE dynamic_id=?",
                (dynamic_id,),
            ).fetchone()
            if stored != fingerprint:
                message = "Frozen media source identity changed"
                raise ValueError(message)
            if attempts >= _MAX_ATTEMPTS or deadline <= now or status == "failed":
                return 0, 0.0
            db.execute(
                "UPDATE media_preparations SET attempts=attempts+1,status='preparing' "
                "WHERE dynamic_id=?",
                (dynamic_id,),
            )
            return attempts + 1, deadline - now

    def finish_media_preparation(
        self, dynamic_id: str, status: str, diagnostics: dict[str, object]
    ) -> None:
        with self._connect() as db:
            row = db.execute(
                "SELECT started,attempts,diagnostics FROM media_preparations "
                "WHERE dynamic_id=?",
                (dynamic_id,),
            ).fetchone()
            if row is None:
                return
            previous = json.loads(row[2])
            diagnostics = {
                **diagnostics,
                "attempts": row[1],
                "elapsed_seconds": round(max(0, self._now() - row[0]), 3),
                "reasons": list(
                    dict.fromkeys(
                        [
                            *_reasons(previous.get("reasons")),
                            *_reasons(diagnostics.get("reasons")),
                        ]
                    )
                ),
            }
            db.execute(
                "UPDATE media_preparations SET status=?,diagnostics=? "
                "WHERE dynamic_id=?",
                (status, json.dumps(diagnostics, sort_keys=True), dynamic_id),
            )

    def load_media_source(self, dynamic_id: str, source_key: str) -> bytes | None:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload FROM media_sources WHERE dynamic_id=? AND source_key=?",
                (dynamic_id, source_key),
            ).fetchone()
        if row is None:
            return None
        message = decode_media(row[0], self.media_root)
        if (
            message
            and len(message.parts) == 1
            and isinstance(message.parts[0], BinaryImagePart)
        ):
            return message.parts[0].content
        error = "Invalid frozen media source"
        raise ValueError(error)

    def save_media_source(
        self, dynamic_id: str, source_key: str, content: bytes
    ) -> None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            payload = encode_media(
                OutboundMessage(
                    (BinaryImagePart(content, "application/octet-stream"),)
                ),
                self.media_root,
            )
            db.execute(
                "INSERT OR IGNORE INTO media_sources VALUES (?,?,?)",
                (dynamic_id, source_key, payload),
            )
