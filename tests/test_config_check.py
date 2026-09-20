from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ironsbot.config.loader import load_settings
from ironsbot.config_check import CONFIG_ERROR_EXIT_CODE, configuration_summary

ROOT = Path(__file__).resolve().parents[1]


def test_configuration_summary_reports_selection_without_credentials() -> None:
    settings = load_settings(ROOT / "config.example.toml", env={})

    assert configuration_summary(settings) == (
        "IronsBot configuration valid.",
        "Outbound platform: onebot",
        "QQ Official accounts: none",
        "OneBot enabled: true",
        "OneBot outbound enabled: true",
        "OneBot identity verification: false",
        "AI providers: none",
    )


def test_config_check_reports_aliases_without_secret_values() -> None:
    app_id = "10001"
    secret = "test-app-secret-private"
    ai_key = "test-ai-key-private"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ironsbot.config_check",
            "--no-dotenv",
            "--config",
            str(ROOT / "config.example.toml"),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "APP_SECRET_10001": secret,
            "AI_KEY_DEEPSEEK": ai_key,
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )

    assert result.returncode == 0, result.stderr
    assert "Outbound platform: qq_official" in result.stdout
    assert "QQ Official accounts: example_bot" in result.stdout
    assert "OneBot outbound enabled: false" in result.stdout
    assert "AI providers: deepseek(1 models)" in result.stdout
    assert app_id not in result.stdout
    assert secret not in result.stdout
    assert ai_key not in result.stdout


def test_config_check_redacts_secret_from_validation_error(tmp_path: Path) -> None:
    secret = "secret-value-that-must-not-leak"
    config_path = tmp_path / "invalid.toml"
    config_path.write_text(
        '[ai]\nprovider_order = ["missing"]\n'
        '[ai.providers.missing]\nbase_url = "https://example.invalid"\n'
        'models = ["model"]\nunknown = "secret-value-that-must-not-leak"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ironsbot.config_check",
            "--no-dotenv",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env={**os.environ, "AI_KEY_MISSING": secret},
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )

    assert result.returncode == CONFIG_ERROR_EXIT_CODE
    assert "IronsBot configuration invalid" in result.stderr
    assert "unknown" in result.stderr
    assert secret not in result.stderr
    assert "Traceback" not in result.stderr


def test_config_check_rejects_undeclared_official_policy_target(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "invalid-official-policy.toml"
    text = (ROOT / "config.example.toml").read_text(encoding="utf-8")
    text = text.replace(
        "[bot.qq_official.accounts.example_bot.user_policy]",
        "[bot.qq_official.accounts.example_bot.user_policy]\n"
        '"raw-official-openid" = ["help"]',
    )
    config_path.write_text(text, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ironsbot.config_check",
            "--no-dotenv",
            "--config",
            str(config_path),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "APP_SECRET_10001": "example-secret",
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=15,
    )

    assert result.returncode == CONFIG_ERROR_EXIT_CODE
    assert "IronsBot configuration invalid" in result.stderr
    assert "has no official endpoint for account example_bot" in result.stderr
    assert "Traceback" not in result.stderr
