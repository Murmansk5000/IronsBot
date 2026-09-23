from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_application_logging_routes_stdlib_records_to_nonebot() -> None:
    from nonebot.log import logger

    from ironsbot.app.bootstrap import configure_application_logging

    application_logger = logging.getLogger("ironsbot")
    previous_handlers = application_logger.handlers[:]
    previous_level = application_logger.level
    messages: list[str] = []
    sink_id = logger.add(
        lambda message: messages.append(str(message)),
        format="{message}",
        level="INFO",
    )
    try:
        application_logger.handlers.clear()
        configure_application_logging("INFO")
        logging.getLogger("ironsbot.acceptance").info("stdlib bridge ready")
    finally:
        logger.remove(sink_id)
        application_logger.handlers[:] = previous_handlers
        application_logger.setLevel(previous_level)

    assert any("stdlib bridge ready" in message for message in messages)


def test_application_bootstrap_smoke(tmp_path: Path) -> None:
    config = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    config = config.replace('environment = "prod"', 'environment = "test"', 1)
    config = config.replace(
        'qq_state = "data/state/qq_state.sqlite"',
        f'qq_state = "{(tmp_path / "qq_state.sqlite").as_posix()}"',
    )
    config_path = tmp_path / "bootstrap.toml"
    config_path.write_text(config, encoding="utf-8")
    script = """
import os
import inspect
import nonebot
from copy import deepcopy
from functools import partial
from typing import ForwardRef

from nonebot.log import logger
from nonebot.dependencies import utils
import nonebot.dependencies as dependencies
from nonebot.utils import is_coroutine_callable

logger.remove()

unresolved_annotations = []
current_call = [None]
original_get_typed_annotation = utils.get_typed_annotation
original_get_typed_signature = dependencies.get_typed_signature

def checked_get_typed_annotation(parameter, globalns):
    if isinstance(parameter.annotation, str):
        try:
            utils.evaluate_forwardref(
                ForwardRef(parameter.annotation),
                globalns,
                globalns,
            )
        except Exception as error:
            call = current_call[0]
            source = getattr(call, "func", call)
            unresolved_annotations.append(
                f"{getattr(source, '__module__', '<unknown>')}:"
                f"{getattr(source, '__qualname__', repr(source))}."
                f"{parameter.name}={parameter.annotation} ({error})"
            )
    return original_get_typed_annotation(parameter, globalns)

def checked_get_typed_signature(call):
    previous = current_call[0]
    current_call[0] = call
    try:
        return original_get_typed_signature(call)
    finally:
        current_call[0] = previous

utils.get_typed_annotation = checked_get_typed_annotation
dependencies.get_typed_signature = checked_get_typed_signature

from ironsbot.app.bootstrap import bootstrap

state = bootstrap()
assert nonebot.get_driver().env == "test"
assert os.environ["ENVIRONMENT"] == "outer"
messages = []
privacy_sink = logger.add(messages.append, format="{message}")
actor_id = "1" * 10
try:
    logger.info(
        "secret={} actor={}",
        os.environ["APP_SECRET_10001"],
        actor_id,
    )
finally:
    logger.remove(privacy_sink)
rendered = "".join(messages)
assert "test-secret" not in rendered
assert actor_id not in rendered
assert "<secret:" in rendered
assert "<id:" in rendered
assert not unresolved_annotations, "\\n".join(unresolved_annotations)
assert state.lifecycle is not None
assert [name for name, _hook in state.lifecycle.resource_startup_hooks] == [
    "identity_links",
    "data_sync",
    "qq_official",
    "bilibili_official_recovery",
]
assert {"seer.team.query", "seer.pet.avatar"}.issubset(
    state.resources.commands.qq_official_direct_command_ids
)
assert len(state.contributions) > 0
assert not state.onebot_message_handling_enabled
assert len(state.matcher_factory.message_matchers) == 0
assert len(state.matcher_factory.notice_matchers) == 0
assert state.resources.onebot_ingress is not None
assert len({plugin.id for plugin in state.contributions}) == len(state.contributions)

for matcher in (
    *state.matcher_factory.message_matchers,
    *state.matcher_factory.notice_matchers,
):
    deepcopy(matcher._default_state)
    dependencies = (*matcher.rule.checkers, *matcher.handlers)
    for dependency in dependencies:
        call = dependency.call
        wraps_async = (
            isinstance(call, partial)
            and inspect.iscoroutinefunction(call.func)
        )
        assert not wraps_async or is_coroutine_callable(call), (
            f"unrecognized async partial in {matcher}: {call}"
        )

print("BOOTSTRAP_OK")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=30,
        env={
            **dict(os.environ),
            "ENVIRONMENT": "outer",
            "APP_CONFIG_PATH": str(config_path),
            "APP_SECRET_10001": "test-secret",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "BOOTSTRAP_OK"
