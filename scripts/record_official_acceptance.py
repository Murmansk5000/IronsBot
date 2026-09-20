# SPDX-License-Identifier: MIT
"""Render one redacted QQ Official live-acceptance evidence record as JSON.

This tool validates explicitly supplied observations. It does not inspect production
configuration, connect to QQ, or decide that a test passed from application logs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Final, Literal

AcceptanceConclusion = Literal["pass", "fail", "not-enabled", "external-gate"]
PlatformEvidenceKind = Literal[
    "accepted",
    "rejected",
    "none-observed",
    "not-applicable",
]
INVALID_EVIDENCE_EXIT_CODE: Final = 2

_ACCEPTANCE_ROWS: Final = frozenset(
    (
        *(f"A{index}" for index in range(1, 13)),
        *(f"B{index}" for index in range(1, 10)),
        *(f"C{index}" for index in range(1, 10)),
    )
)
_REVISION_PATTERN: Final = re.compile(r"[0-9a-f]{40}")
_DIGEST_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}")
_FINGERPRINT_PATTERN: Final = re.compile(r"[a-z][a-z0-9_-]{0,31}:[0-9a-f]{10,64}")
_RAW_OPENID_PATTERN: Final = re.compile(r"(?<![A-Za-z0-9])[A-F0-9]{32}(?![A-Za-z0-9])")
_RAW_NUMERIC_ID_PATTERN: Final = re.compile(r"(?<![A-Za-z0-9])\d{7,}(?![A-Za-z0-9])")
_SECRET_ASSIGNMENT_PATTERN: Final = re.compile(
    r"(?i)(?:app[ _-]?id|secret|token|password|api[ _-]?key|openid|qq)\s*[:=]\s*\S+"
)
_OPAQUE_CREDENTIAL_PATTERN: Final = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z0-9_-]{24,}(?![A-Za-z0-9])"
)


class AcceptanceEvidenceError(ValueError):
    """Raised when a live-acceptance record is incomplete or unsafe."""

    @classmethod
    def invalid_row(cls, row: str) -> AcceptanceEvidenceError:
        return cls(f"unknown acceptance row: {row!r}")

    @classmethod
    def invalid_revision(cls) -> AcceptanceEvidenceError:
        return cls("revision must be a full 40-character lowercase Git SHA")

    @classmethod
    def invalid_digest(cls) -> AcceptanceEvidenceError:
        return cls("image digest must use sha256:<64 lowercase hex characters>")

    @classmethod
    def invalid_fingerprint(cls) -> AcceptanceEvidenceError:
        return cls(
            "account fingerprint must use <alias>:<10-64 lowercase hex characters>"
        )

    @classmethod
    def pass_without_client_observation(cls) -> AcceptanceEvidenceError:
        return cls("pass requires a client-visible observation")

    @classmethod
    def pass_without_platform_evidence(cls) -> AcceptanceEvidenceError:
        return cls("pass requires platform or redacted log evidence")

    @classmethod
    def invalid_timestamp(cls) -> AcceptanceEvidenceError:
        return cls("observed-at must be an ISO 8601 timestamp")

    @classmethod
    def missing_timezone(cls) -> AcceptanceEvidenceError:
        return cls("observed-at must include an explicit timezone offset")

    @classmethod
    def empty_field(cls, name: str) -> AcceptanceEvidenceError:
        return cls(f"{name} must not be empty")

    @classmethod
    def unsafe_field(cls, name: str) -> AcceptanceEvidenceError:
        return cls(f"{name} contains a raw identifier or credential-like value")


@dataclass(frozen=True, slots=True)
class AcceptanceEvidenceDraft:
    row: str
    revision: str
    image_digest: str
    observed_at: str
    account_fingerprint: str
    context: str
    expected: str
    actual: str
    client_observed: bool
    platform_evidence_kind: PlatformEvidenceKind
    platform_evidence: str
    conclusion: AcceptanceConclusion
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class AcceptanceEvidence:
    schema_version: int
    row: str
    revision: str
    image_digest: str
    observed_at: str
    account_fingerprint: str
    context: str
    expected: str
    actual: str
    client_observed: bool
    platform_evidence_kind: PlatformEvidenceKind
    platform_evidence: str
    conclusion: AcceptanceConclusion
    notes: str | None = None


def build_evidence(draft: AcceptanceEvidenceDraft) -> AcceptanceEvidence:
    normalized_row = draft.row.upper()
    if normalized_row not in _ACCEPTANCE_ROWS:
        raise AcceptanceEvidenceError.invalid_row(draft.row)
    if _REVISION_PATTERN.fullmatch(draft.revision) is None:
        raise AcceptanceEvidenceError.invalid_revision()
    if _DIGEST_PATTERN.fullmatch(draft.image_digest) is None:
        raise AcceptanceEvidenceError.invalid_digest()
    _validate_observed_at(draft.observed_at)
    if _FINGERPRINT_PATTERN.fullmatch(draft.account_fingerprint) is None:
        raise AcceptanceEvidenceError.invalid_fingerprint()

    text_fields = {
        "context": draft.context,
        "expected": draft.expected,
        "actual": draft.actual,
        "platform_evidence": draft.platform_evidence,
    }
    if draft.notes is not None:
        text_fields["notes"] = draft.notes
    for name, value in text_fields.items():
        _validate_redacted_text(name, value)

    if draft.conclusion == "pass" and not draft.client_observed:
        raise AcceptanceEvidenceError.pass_without_client_observation()
    if draft.conclusion == "pass" and draft.platform_evidence_kind == "not-applicable":
        raise AcceptanceEvidenceError.pass_without_platform_evidence()

    return AcceptanceEvidence(
        schema_version=1,
        row=normalized_row,
        revision=draft.revision,
        image_digest=draft.image_digest,
        observed_at=draft.observed_at,
        account_fingerprint=draft.account_fingerprint,
        context=draft.context,
        expected=draft.expected,
        actual=draft.actual,
        client_observed=draft.client_observed,
        platform_evidence_kind=draft.platform_evidence_kind,
        platform_evidence=draft.platform_evidence,
        conclusion=draft.conclusion,
        notes=draft.notes,
    )


def render_evidence(evidence: AcceptanceEvidence) -> str:
    return json.dumps(asdict(evidence), ensure_ascii=False, indent=2) + "\n"


def _validate_observed_at(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise AcceptanceEvidenceError.invalid_timestamp() from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AcceptanceEvidenceError.missing_timezone()


def _validate_redacted_text(name: str, value: str) -> None:
    if not value.strip():
        raise AcceptanceEvidenceError.empty_field(name)
    patterns = (
        _RAW_OPENID_PATTERN,
        _RAW_NUMERIC_ID_PATTERN,
        _SECRET_ASSIGNMENT_PATTERN,
        _OPAQUE_CREDENTIAL_PATTERN,
    )
    if any(pattern.search(value) is not None for pattern in patterns):
        raise AcceptanceEvidenceError.unsafe_field(name)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and render one redacted QQ Official acceptance record."
    )
    parser.add_argument("--row", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--observed-at", required=True)
    parser.add_argument("--account-fingerprint", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--actual", required=True)
    parser.add_argument("--client-observed", action="store_true")
    parser.add_argument(
        "--platform-evidence-kind",
        choices=("accepted", "rejected", "none-observed", "not-applicable"),
        required=True,
    )
    parser.add_argument("--platform-evidence", required=True)
    parser.add_argument(
        "--conclusion",
        choices=("pass", "fail", "not-enabled", "external-gate"),
        required=True,
    )
    parser.add_argument("--notes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        evidence = build_evidence(
            AcceptanceEvidenceDraft(
                row=args.row,
                revision=args.revision,
                image_digest=args.image_digest,
                observed_at=args.observed_at,
                account_fingerprint=args.account_fingerprint,
                context=args.context,
                expected=args.expected,
                actual=args.actual,
                client_observed=args.client_observed,
                platform_evidence_kind=args.platform_evidence_kind,
                platform_evidence=args.platform_evidence,
                conclusion=args.conclusion,
                notes=args.notes,
            )
        )
    except AcceptanceEvidenceError as error:
        sys.stderr.write(f"invalid acceptance evidence: {error}\n")
        return INVALID_EVIDENCE_EXIT_CODE
    sys.stdout.write(render_evidence(evidence))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
