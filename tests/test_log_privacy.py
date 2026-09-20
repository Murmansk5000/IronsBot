from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.log import logger
from pydantic import ValidationError

from ironsbot.app.log_privacy import LogPrivacyRedactor, configure_log_privacy
from ironsbot.config.models.settings import Settings

if TYPE_CHECKING:
    from loguru import Record

ROOT = Path(__file__).resolve().parents[1]
_TEST_QQ_ID = "1" * 10
_TEST_OPENID = "A1" * 16
_RAW_OPENID = re.compile(r"(?<![A-Za-z0-9])[A-F0-9]{32}(?![A-Za-z0-9])")
_TEXT_ROOTS = (
    ROOT / ".github",
    ROOT / "docker",
    ROOT / "docs",
    ROOT / "ironsbot",
    ROOT / "scripts",
    ROOT / "templates",
    ROOT / "tests",
)
_TEXT_FILES = (
    ROOT / ".env.example",
    ROOT / "ARCHITECTURE.md",
    ROOT / "Dockerfile",
    ROOT / "README.md",
    ROOT / "config.example.toml",
    ROOT / "docker-compose.yml",
)
_TEXT_SUFFIXES = frozenset({".json", ".md", ".py", ".toml", ".xml", ".yaml", ".yml"})


def _record(message: str, exception: BaseException | None = None) -> Record:
    record = {
        "message": message,
        "exception": (
            None
            if exception is None
            else SimpleNamespace(
                type=type(exception),
                value=exception,
                traceback=exception.__traceback__,
            )
        ),
    }
    return cast("Record", record)


def test_log_privacy_redacts_secrets_and_transport_identifiers() -> None:
    secret = "top-secret-value"
    redactor = LogPrivacyRedactor.from_environment(
        {
            "APP_SECRET_10001": secret,
            "UNRELATED": "keep-this-value",
        }
    )
    record = _record(
        f"secret={secret} qq={_TEST_QQ_ID} "
        f"openid={_TEST_OPENID} "
        "revision=7aa0be304ed6c2a0c9e2ebc669c40a5c639b66ae"
    )

    redactor(record)

    message = str(record["message"])
    assert secret not in message
    assert _TEST_QQ_ID not in message
    assert _TEST_OPENID not in message
    assert "7aa0be304ed6c2a0c9e2ebc669c40a5c639b66ae" in message
    assert message.count("<secret:") == 1
    assert message.count("<id:") == 1
    assert message.count("<openid:") == 1


def test_log_privacy_redacts_exception_text_without_loguru_reformatting() -> None:
    secret = "exception-secret"
    redactor = LogPrivacyRedactor((secret,))
    exception = RuntimeError()
    exception.args = (f"failed for {secret} and {_TEST_QQ_ID}",)
    record = _record("request failed", exception)

    redactor(record)

    assert record["exception"] is None
    message = str(record["message"])
    assert "RuntimeError" in message
    assert secret not in message
    assert _TEST_QQ_ID not in message
    assert "<secret:" in message
    assert "<id:" in message


def test_configured_patcher_redacts_every_loguru_sink() -> None:
    secret = "sink-secret-value"
    messages: list[str] = []
    sink_id = logger.add(messages.append, format="{message}")
    try:
        configure_log_privacy({"AI_KEY_DEEPSEEK": secret})
        logger.info("key={} actor={}", secret, _TEST_QQ_ID)
    finally:
        logger.remove(sink_id)
        logger.configure(patcher=None)

    rendered = "".join(messages)
    assert secret not in rendered
    assert _TEST_QQ_ID not in rendered
    assert "<secret:" in rendered
    assert "<id:" in rendered


def test_settings_validation_never_renders_secret_input() -> None:
    secret = "validation-secret-value"

    with pytest.raises(ValidationError) as captured:
        Settings.model_validate(
            {
                "bot": {
                    "qq_official": {
                        "accounts": {
                            "local_bot": {
                                "app_id": "validation-app",
                                "secret": secret,
                                "unknown": True,
                            }
                        }
                    }
                }
            }
        )

    assert secret not in str(captured.value)


def test_repository_does_not_embed_raw_openids() -> None:
    paths = [
        *(_TEXT_FILES),
        *(
            path
            for root in _TEXT_ROOTS
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in _TEXT_SUFFIXES
        ),
    ]
    violations: list[str] = []
    for path in sorted(set(paths)):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(),
            start=1,
        ):
            if _RAW_OPENID.search(line):
                violations.append(f"{path.relative_to(ROOT)}:{line_number}")

    assert not violations, "raw OpenID literals: " + ", ".join(violations)
