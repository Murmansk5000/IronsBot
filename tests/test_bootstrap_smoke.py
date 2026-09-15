from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_application_bootstrap_smoke(tmp_path: Path) -> None:
    config = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    qq_start = config.index("[bot.qq_official]")
    account_start = config.index("[bot.qq_official.accounts.example_bot]")
    qq_section = config[qq_start:account_start].replace(
        "enabled = false", "enabled = true", 1
    )
    config = config[:qq_start] + qq_section + config[account_start:]
    account_start = config.index("[bot.qq_official.accounts.example_bot]")
    account_end = config.index("[", account_start + 1)
    account = config[account_start:account_end]
    account = account.replace("enabled = false", "enabled = true", 1)
    config = config[:account_start] + account + config[account_end:]
    config_path = tmp_path / "bootstrap.toml"
    config_path.write_text(config, encoding="utf-8")
    script = """
import os
import inspect
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
assert not unresolved_annotations, "\\n".join(unresolved_annotations)
assert state.lifecycle is not None
assert len(state.resources.commands.qq_official_direct_command_ids) == 78
assert len(state.contributions) > 0
assert len(state.matcher_factory.message_matchers) > 0
assert len(state.matcher_factory.notice_matchers) > 0
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
            "APP_CONFIG_PATH": str(config_path),
            "QQ_OFFICIAL_APP_ID_EXAMPLE_BOT": "example-app",
            "QQ_OFFICIAL_SECRET_EXAMPLE_BOT": "test-secret",
        },
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "BOOTSTRAP_OK"
