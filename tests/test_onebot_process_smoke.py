from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from http import HTTPStatus
from pathlib import Path
from typing import Any, cast

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response
from websockets.sync.client import ClientConnection, connect

BOT_ID = 111111111
USER_ID = 123456789
GROUP_ID = 456
STARTUP_TIMEOUT_SECONDS = 30.0
HANDSHAKE_TIMEOUT_SECONDS = 5.0
REPLY_TIMEOUT_SECONDS = 15.0
ROOT = Path(__file__).resolve().parents[1]
ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class OneBotSocketStartupError(AssertionError):
    pass


class OneBotReplyMissingError(AssertionError):
    pass


def _unused_local_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _config(port: int) -> str:
    return f"""
[bot]
environment = "test"
host = "127.0.0.1"
port = {port}
log_level = "INFO"
plugin_manifest = "core"
superusers = [{USER_ID}]
use_default_for_unconfigured_targets = true

[identities.groups]
smoke_group = {{ qq = {GROUP_ID} }}

[bot.onebot.routing]
enabled = false
default_bot = "smoke_bot"

[bot.onebot.routing.bot_aliases]
smoke_bot = {BOT_ID}

[bot.onebot.self_commands]
enabled = true
prefixes = ["demo "]

[operations.data_sync]
on_startup = false
interval_enabled = false

[operations.startup_notice]
enabled = false

[operations.clock_check]
enabled = false

[operations.docker_update]
check_on_startup = false
""".strip()


def _private_about_event() -> dict[str, Any]:
    return {
        "time": int(time.time()),
        "self_id": BOT_ID,
        "post_type": "message",
        "message_type": "private",
        "sub_type": "friend",
        "message_id": 1,
        "user_id": USER_ID,
        "message": [{"type": "text", "data": {"text": "关于"}}],
        "raw_message": "关于",
        "font": 0,
        "sender": {
            "user_id": USER_ID,
            "nickname": "process-smoke",
            "sex": "unknown",
            "age": 0,
        },
    }


def _connect_when_ready(port: int) -> ClientConnection:
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: OSError | InvalidStatus | None = None
    handshake_timed_out = False
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            return connect(
                f"ws://127.0.0.1:{port}/onebot/v11/ws",
                additional_headers={"X-Self-ID": str(BOT_ID)},
                proxy=None,
                open_timeout=min(HANDSHAKE_TIMEOUT_SECONDS, remaining),
            )
        except InvalidStatus as error:
            # A timed-out handshake may have registered the bot before the
            # server processes its disconnect. Never retry an initial 403.
            if (
                error.response.status_code != HTTPStatus.FORBIDDEN
                or not handshake_timed_out
            ):
                raise
            last_error = error
        except OSError as error:
            last_error = error
            if isinstance(error, TimeoutError):
                handshake_timed_out = True
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    raise OneBotSocketStartupError from last_error


def test_connect_retries_duplicate_bot_403_only_after_handshake_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = cast("ClientConnection", object())
    outcomes: list[Exception | ClientConnection] = [
        TimeoutError(),
        InvalidStatus(Response(403, "Forbidden", Headers())),
        connection,
    ]
    timeouts: list[float] = []

    def scripted_connect(
        _url: str,
        *,
        additional_headers: dict[str, str],
        open_timeout: float,
        proxy: None,
    ) -> ClientConnection:
        assert proxy is None
        assert additional_headers == {"X-Self-ID": str(BOT_ID)}
        timeouts.append(open_timeout)
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(f"{__name__}.connect", scripted_connect)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    assert _connect_when_ready(12345) is connection
    assert timeouts == [HANDSHAKE_TIMEOUT_SECONDS] * 3


@pytest.mark.parametrize("prior_error", [None, ConnectionRefusedError()])
def test_connect_does_not_retry_authentication_403(
    monkeypatch: pytest.MonkeyPatch,
    prior_error: OSError | None,
) -> None:
    rejection = InvalidStatus(Response(403, "Forbidden", Headers()))
    outcomes = [prior_error, rejection] if prior_error is not None else [rejection]
    calls: list[str] = []

    def rejected_connect(url: str, **_kwargs: object) -> ClientConnection:
        calls.append(url)
        raise outcomes.pop(0)

    expected_calls = len(outcomes)
    monkeypatch.setattr(f"{__name__}.connect", rejected_connect)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    with pytest.raises(InvalidStatus) as error:
        _connect_when_ready(12345)
    assert error.value is rejection
    assert len(calls) == expected_calls


def test_connect_handshake_retries_share_total_startup_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    elapsed = [0.0]
    timeouts: list[float] = []

    def timeout_connect(
        _url: str, *, open_timeout: float, **_kwargs: object
    ) -> ClientConnection:
        timeouts.append(open_timeout)
        elapsed[0] += open_timeout
        raise TimeoutError

    def advance(seconds: float) -> None:
        elapsed[0] += seconds

    monkeypatch.setattr(f"{__name__}.connect", timeout_connect)
    monkeypatch.setattr(time, "monotonic", lambda: elapsed[0])
    monkeypatch.setattr(time, "sleep", advance)
    with pytest.raises(OneBotSocketStartupError):
        _connect_when_ready(12345)
    assert elapsed[0] == STARTUP_TIMEOUT_SECONDS
    assert all(0 < timeout <= HANDSHAKE_TIMEOUT_SECONDS for timeout in timeouts)


def _reply_text(action: dict[str, Any]) -> str:
    message = action.get("params", {}).get("message", [])
    if isinstance(message, str):
        return message
    return "".join(
        str(segment.get("data", {}).get("text", ""))
        for segment in message
        if isinstance(segment, dict) and segment.get("type") == "text"
    )


def _assert_about_reply(action: dict[str, Any], *, self_command: bool) -> None:
    assert "IronsBot" in _reply_text(action)
    assert "版本：" in _reply_text(action)
    if self_command:
        assert action["params"]["group_id"] == GROUP_ID
        segments = action["params"]["message"]
        assert segments[0] == {"type": "reply", "data": {"id": "-123"}}
        assert all(part["type"] != "at" for part in segments)
    else:
        assert action["params"]["user_id"] == USER_ID


@pytest.mark.parametrize("self_command", [False, True])
def test_full_process_handles_onebot_websocket_event(
    tmp_path: Path, *, self_command: bool
) -> None:
    port = _unused_local_port()
    config_path = tmp_path / "ironsbot.toml"
    config_path.write_text(_config(port), encoding="utf-8")
    log_path = tmp_path / "process.log"
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.startswith(("QQ_OFFICIAL_", "APP_ID_", "APP_SECRET_")):
            del environment[key]
    environment.pop("ONEBOT_ACCESS_TOKEN", None)
    environment["APP_CONFIG_PATH"] = str(config_path)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(ROOT), environment.get("PYTHONPATH", "")))
    )

    reply_received = False
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "-m", "ironsbot"],
            cwd=tmp_path,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            with _connect_when_ready(port) as websocket:
                event = _private_about_event()
                if self_command:
                    event.update(
                        post_type="message_sent",
                        message_type="group",
                        sub_type="normal",
                        group_id=GROUP_ID,
                        user_id=BOT_ID,
                        message_id=-123,
                        raw_message="demo 关于",
                        message=[{"type": "text", "data": {"text": "demo 关于"}}],
                        sender={"user_id": BOT_ID, "role": "member"},
                    )
                websocket.send(json.dumps(event))
                deadline = time.monotonic() + REPLY_TIMEOUT_SECONDS
                try:
                    while time.monotonic() < deadline:
                        action = json.loads(
                            websocket.recv(timeout=deadline - time.monotonic())
                        )
                        echo = action.get("echo")
                        if action.get("action") in {
                            "send_msg",
                            "send_private_msg",
                            "send_group_msg",
                        }:
                            websocket.send(
                                json.dumps(
                                    {
                                        "status": "ok",
                                        "retcode": 0,
                                        "data": {"message_id": 2},
                                        "echo": echo,
                                    }
                                )
                            )
                            _assert_about_reply(action, self_command=self_command)
                            reply_received = True
                            break
                        websocket.send(
                            json.dumps(
                                {
                                    "status": "ok",
                                    "retcode": 0,
                                    "data": {},
                                    "echo": echo,
                                }
                            )
                        )
                except TimeoutError:
                    pass
                if not reply_received:
                    raise OneBotReplyMissingError
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    assert reply_received
    log_text = ANSI_ESCAPE.sub("", log_path.read_text(encoding="utf-8"))
    assert "Application startup complete" in log_text
    assert "Unknown ForwardRef" not in log_text
