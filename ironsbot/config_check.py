# SPDX-License-Identifier: MIT
"""Validate deployment configuration without starting application resources."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import ValidationError

from ironsbot.app.log_privacy import LogPrivacyRedactor
from ironsbot.config.environment import load_runtime_environment
from ironsbot.config.loader import (
    CONFIG_ENV,
    ConfigFileNotFoundError,
    TOMLDecodeError,
    load_settings,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping, Sequence

    from ironsbot.config.models.settings import Settings

CONFIG_ERROR_EXIT_CODE = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate IronsBot TOML and deployment variables without starting "
            "NoneBot, QQ Official, schedulers, databases, or network clients."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=f"TOML path; defaults to {CONFIG_ENV} or config/ironsbot.toml.",
    )
    parser.add_argument(
        "--no-dotenv",
        action="store_true",
        help="Use process/container variables only; do not load .env files.",
    )
    return parser


def _format_aliases(values: Sequence[str]) -> str:
    return ", ".join(values) if values else "none"


def configuration_summary(settings: Settings) -> tuple[str, ...]:
    selection = settings.outbound_platform_selection
    official_accounts = tuple(settings.bot.qq_official.enabled_accounts)
    ai_providers = tuple(
        f"{alias}({len(provider.models)} models)"
        for alias, provider in settings.ai.configured_providers
    )
    return (
        "IronsBot configuration valid.",
        f"Outbound platform: {selection.platform.value}",
        f"QQ Official accounts: {_format_aliases(official_accounts)}",
        f"OneBot enabled: {str(settings.bot.onebot.enabled).lower()}",
        f"OneBot outbound enabled: {str(selection.onebot_outbound_enabled).lower()}",
        (
            "OneBot identity verification: "
            f"{str(settings.bot.onebot.identity_verification).lower()}"
        ),
        f"AI providers: {_format_aliases(ai_providers)}",
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    env: MutableMapping[str, str] | None = None,
    directory: Path | None = None,
) -> int:
    args = _parser().parse_args(argv)
    values = os.environ if env is None else env
    if not args.no_dotenv:
        load_runtime_environment(directory=directory, env=values)

    try:
        settings = load_settings(args.config, env=values)
    except (
        ConfigFileNotFoundError,
        TOMLDecodeError,
        ValidationError,
        TypeError,
        ValueError,
    ) as error:
        redactor = LogPrivacyRedactor.from_environment(values)
        sys.stderr.write(
            f"IronsBot configuration invalid:\n{redactor.redact(str(error))}\n"
        )
        return CONFIG_ERROR_EXIT_CODE

    sys.stdout.write("\n".join(configuration_summary(settings)) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
