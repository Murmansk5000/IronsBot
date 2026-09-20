# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scripts.record_official_acceptance import (
    INVALID_EVIDENCE_EXIT_CODE,
    AcceptanceEvidenceDraft,
    build_evidence,
    main,
    render_evidence,
)

REVISION = "a" * 40
IMAGE_DIGEST = f"sha256:{'b' * 64}"


def _valid_draft() -> AcceptanceEvidenceDraft:
    return AcceptanceEvidenceDraft(
        row="C4",
        revision=REVISION,
        image_digest=IMAGE_DIGEST,
        observed_at="2026-09-20T12:30:00+08:00",
        account_fingerprint="local_bot:0123456789",
        context="隔离测试群触发受控后台失败",
        expected="普通群不显示管理异常",
        actual="观察窗口内只有触发消息和通用用户回复",
        client_observed=True,
        platform_evidence_kind="none-observed",
        platform_evidence="脱敏日志窗口未出现管理通知投递",
        conclusion="pass",
    )


def test_build_evidence_renders_complete_redacted_record() -> None:
    evidence = build_evidence(_valid_draft())

    rendered = json.loads(render_evidence(evidence))

    assert rendered["schema_version"] == 1
    assert rendered["row"] == "C4"
    assert rendered["revision"] == REVISION
    assert rendered["image_digest"] == IMAGE_DIGEST
    assert rendered["client_observed"] is True
    assert rendered["conclusion"] == "pass"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("context", "用户 123456789 触发命令"),
        ("actual", f"member_openid={'A' * 32}"),
        ("expected", "secret=synthetic-test-secret"),
        ("platform_evidence", f"receipt {'SyntheticCredential' * 2}"),
    ],
)
def test_build_evidence_rejects_raw_identity_or_credential(
    field: str,
    value: str,
) -> None:
    draft = replace(_valid_draft(), **{field: value})

    with pytest.raises(ValueError, match="raw identifier or credential-like value"):
        build_evidence(draft)


def test_build_evidence_requires_exact_revision_digest_and_timezone() -> None:
    draft = replace(_valid_draft(), revision="abc123")
    with pytest.raises(ValueError, match="full 40-character"):
        build_evidence(draft)

    draft = replace(_valid_draft(), image_digest="latest")
    with pytest.raises(ValueError, match="sha256"):
        build_evidence(draft)

    draft = replace(_valid_draft(), observed_at="2026-09-20T12:30:00")
    with pytest.raises(ValueError, match="timezone"):
        build_evidence(draft)


def test_pass_requires_client_and_platform_evidence() -> None:
    draft = replace(_valid_draft(), client_observed=False)
    with pytest.raises(ValueError, match="client-visible"):
        build_evidence(draft)

    draft = replace(_valid_draft(), platform_evidence_kind="not-applicable")
    with pytest.raises(ValueError, match="platform or redacted log"):
        build_evidence(draft)


def test_cli_prints_json_without_writing_files(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "--row",
            "A7",
            "--revision",
            REVISION,
            "--image-digest",
            IMAGE_DIGEST,
            "--observed-at",
            "2026-09-20T12:30:00+08:00",
            "--account-fingerprint",
            "public_bot:abcdef0123",
            "--context",
            "受控 C2C 查询幸运橱窗",
            "--expected",
            "确认菜单和最终图片可见",
            "--actual",
            "客户端显示一次菜单和一张图片",
            "--client-observed",
            "--platform-evidence-kind",
            "accepted",
            "--platform-evidence",
            "腾讯回执分类为成功，原始标识已脱敏",
            "--conclusion",
            "pass",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert json.loads(captured.out)["row"] == "A7"


def test_cli_returns_error_for_unredacted_evidence(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "--row",
            "C8",
            "--revision",
            REVISION,
            "--image-digest",
            IMAGE_DIGEST,
            "--observed-at",
            "2026-09-20T12:30:00+08:00",
            "--account-fingerprint",
            "public_bot:abcdef0123",
            "--context",
            "向 123456789 主动发送",
            "--expected",
            "平台明确拒绝",
            "--actual",
            "平台明确拒绝",
            "--client-observed",
            "--platform-evidence-kind",
            "rejected",
            "--platform-evidence",
            "脱敏错误分类",
            "--conclusion",
            "pass",
        ]
    )

    captured = capsys.readouterr()
    assert result == INVALID_EVIDENCE_EXIT_CODE
    assert captured.out == ""
    assert "raw identifier" in captured.err
