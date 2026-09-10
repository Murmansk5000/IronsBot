# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import hashlib
import logging
import struct
from typing import Any

import pytest

from ironsbot.app.lifecycle import TaskOwner
from ironsbot.core.rank_lookup_context import rank_query_id
from ironsbot.integrations.headless_seer.command_id import COMMAND_ID
from ironsbot.integrations.headless_seer.core.connect import SeerEncryptConnect
from ironsbot.integrations.headless_seer.packets.peak import DailyRankParam


@pytest.mark.asyncio
async def test_raw_response_logs_query_worker_digest_without_login_data(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = SeerEncryptConnect(
        asyncio.get_running_loop(),
        spawn=TaskOwner().create,
    )
    packet = struct.pack("!cIII", b"1", 4481, 654321, 0)
    packet += struct.pack("!IIi16s", 1, 200001, 4646, b"player")

    async def recv_bytes() -> bytes:
        return packet

    async def send(*_args: Any) -> None:
        # The reader runs in a different task/context in production.
        token = rank_query_id.set("reader-context")
        try:
            await connection.recv_packet()
        finally:
            rank_query_id.reset(token)

    monkeypatch.setattr(connection, "recv_bytes", recv_bytes)
    monkeypatch.setattr(connection, "send", send)
    token = rank_query_id.set("original-query")
    try:
        with caplog.at_level(logging.INFO):
            await connection.send_and_wait(
                COMMAND_ID.GET_DAILY_RANK_INFO,
                654321,
                DailyRankParam(key=158, sub_key=1, start=0, end=0),
            )
    finally:
        rank_query_id.reset(token)
    assert "rank wire request query=original-query" in caplog.text
    assert "rank wire response query=original-query worker=654321" in caplog.text
    assert "rank wire completion query=original-query worker=654321" in caplog.text
    assert hashlib.sha256(packet).hexdigest() in caplog.text
    assert "reader-context" not in caplog.text
