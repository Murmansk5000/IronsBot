# SPDX-License-Identifier: GPL-3.0-or-later
"""41457 uint32 Unix seconds, verified against the original Flash client."""

import struct
from datetime import datetime, timezone

from ironsbot.services.operations.headless_maintenance import HeadlessMaintenanceEvent


def decode_maintenance_notice(body: bytes | bytearray) -> HeadlessMaintenanceEvent:
    # ServerCloseNoticeController.readUnsignedInt; see the protocol source spec.
    # An exact shape check avoids accepting an undocumented extended payload.
    if len(body) != 4:
        raise ValueError("unexpected maintenance payload length")
    timestamp = struct.unpack("!I", body)[0]
    return HeadlessMaintenanceEvent(
        raw_value=timestamp,
        scheduled_at=datetime.fromtimestamp(timestamp, tz=timezone.utc),
    )
