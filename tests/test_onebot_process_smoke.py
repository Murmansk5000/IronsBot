from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest
from websockets.sync.client import ClientConnection, connect

BOT_ID = 111111111
USER_ID = 123456789
GROUP_ID = 456
STARTUP_TIMEOUT_SECONDS = 30.0
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
driver = "~fastapi+~httpx"
host = "127.0.0.1"
port = {port}
log_level = "INFO"
plugin_manifest = "core"
superusers = [{USER_ID}]

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
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            return connect(
                f"ws://127.0.0.1:{port}/onebot/v11/ws",
                additional_headers={"X-Self-ID": str(BOT_ID)},
                open_timeout=1,
            )
        except OSError as error:  # noqa: PERF203 - bounded process readiness poll
            last_error = error
            time.sleep(0.1)
    raise OneBotSocketStartupError from last_error


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
                            "send_msg", "send_private_msg", "send_group_msg"
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
    assert "Current Env: test" in log_text
