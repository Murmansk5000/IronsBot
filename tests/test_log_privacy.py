from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from nonebot.log import logger
from pydantic import ValidationError

from ironsbot.app.log_privacy import LogPrivacyRedactor, configure_log_privacy
from ironsbot.config.models.settings import Settings

if TYPE_CHECKING:
    from loguru import Record


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
            "QQ_OFFICIAL_SECRET_LOCAL_BOT": secret,
            "UNRELATED": "keep-this-value",
        }
    )
    record = _record(
        f"secret={secret} qq=1621582661 "
        "openid=DEE8BDBAFD1DF10A4A865AD6C4DB773F "
        "revision=7aa0be304ed6c2a0c9e2ebc669c40a5c639b66ae"
    )

    redactor(record)

    message = str(record["message"])
    assert secret not in message
    assert "1621582661" not in message
    assert "DEE8BDBAFD1DF10A4A865AD6C4DB773F" not in message
    assert "7aa0be304ed6c2a0c9e2ebc669c40a5c639b66ae" in message
    assert message.count("<secret:") == 1
    assert message.count("<id:") == 1
    assert message.count("<openid:") == 1


def test_log_privacy_redacts_exception_text_without_loguru_reformatting() -> None:
    secret = "exception-secret"
    redactor = LogPrivacyRedactor((secret,))
    exception = RuntimeError()
    exception.args = (f"failed for {secret} and 1621582661",)
    record = _record("request failed", exception)

    redactor(record)

    assert record["exception"] is None
    message = str(record["message"])
    assert "RuntimeError" in message
    assert secret not in message
    assert "1621582661" not in message
    assert "<secret:" in message
    assert "<id:" in message


def test_configured_patcher_redacts_every_loguru_sink() -> None:
    secret = "sink-secret-value"
    messages: list[str] = []
    sink_id = logger.add(messages.append, format="{message}")
    try:
        configure_log_privacy({"AI_KEY_DEEPSEEK": secret})
        logger.info("key={} actor={}", secret, 1621582661)
    finally:
        logger.remove(sink_id)
        logger.configure(patcher=None)

    rendered = "".join(messages)
    assert secret not in rendered
    assert "1621582661" not in rendered
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
