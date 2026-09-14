# SPDX-License-Identifier: MIT
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from .docker_models import DockerImageCheckResult, DockerUpdateResult

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
DOCKER_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<head>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.\d+)?"
    r"(?P<tz>Z|[+-]\d{2}:\d{2})?$"
)


def format_docker_update_reply(
    *,
    container_name: str,
    image: str,
    result: DockerUpdateResult,
    check_only: bool = False,
) -> str:
    current_version = format_image_version(
        result.current_image_id,
        result.current_image_created,
    )
    target_version = format_image_version(
        result.target_image_id,
        result.target_image_created,
    )
    if result.missing_socket:
        return (
            "Docker 镜像检查已跳过：容器内没有找到 Docker socket。\n"
            "需要给 IronsBot 容器额外挂载：\n"
            "/var/run/docker.sock -> /var/run/docker.sock\n"
            "挂载后再发送 /重启机器人 或 /更新镜像。"
        )

    if result.up_to_date:
        lines = [
            f"Docker 镜像已是最新：{container_name}",
            f"目标镜像：{image}",
            f"镜像ID：{target_version}",
        ]
        if target_commit := visible_image_commit_summary(result.target_image_commit):
            lines.append(f"当前代码：{target_commit}")
        if check_only:
            lines.append("本次只检查，未拉取镜像、未创建 Watchtower、未重启容器。")
        return "\n".join(lines)

    if result.ok:
        current_commit = visible_image_commit_summary(result.current_image_commit)
        target_commit = visible_image_commit_summary(result.target_image_commit)
        lines = [
            (
                f"检测到新镜像：{container_name}"
                if check_only
                else f"检测到新镜像，Docker 自更新任务已启动：{container_name}"
            ),
            f"目标镜像：{image}",
            f"当前镜像ID：{current_version}",
            f"最新镜像ID：{target_version}",
        ]
        if current_commit:
            lines.append(f"当前代码：{current_commit}")
        if target_commit:
            lines.append(f"最新代码：{target_commit}")
        if check_only:
            lines.extend(
                [
                    "结论：检测到远端新镜像，等待确认后更新并重启。",
                    "本次只检查，未拉取镜像、未创建 Watchtower、未重启容器。",
                ]
            )
        else:
            lines.append(
                "接下来 Watchtower 会拉取最新镜像并重建当前容器，"
                "机器人可能会短暂离线；重启后才算真正使用新镜像。"
            )
        return "\n".join(lines)

    return (
        f"Docker 镜像检查失败：{container_name}\n"
        f"目标镜像：{image}\n"
        f"错误：{result.message or '未知错误'}"
    ).rstrip()


def format_docker_update_handoff_reply(
    *,
    container_name: str,
    image: str,
    result: DockerUpdateResult,
) -> str:
    """Format a startup notice only after the target image is verified live."""

    lines = [
        f"Docker 镜像已更新完成：{container_name}",
        f"目标镜像：{image}",
        "当前镜像ID："
        f"{format_image_version(result.target_image_id, result.target_image_created)}",
    ]
    if target_commit := visible_image_commit_summary(result.target_image_commit):
        lines.append(f"当前代码：{target_commit}")
    return "\n".join(lines)


def format_docker_image_check_reply(
    *,
    container_name: str,
    image: str,
    result: DockerImageCheckResult,
) -> str:
    """Format a read-only registry comparison for an administrator."""
    if result.ok and not result.missing_socket:
        return _format_docker_revision_check(container_name, image, result)
    return format_docker_update_reply(
        container_name=container_name,
        image=image,
        result=DockerUpdateResult(
            ok=result.ok,
            message=result.message,
            up_to_date=result.up_to_date,
            current_image_id=result.current_image_id,
            current_image_created=result.current_image_created,
            current_image_commit=result.current_image_commit,
            target_image_id=result.remote_image_id or result.remote_digest,
            target_image_created=result.remote_image_created,
            target_image_commit=result.remote_image_commit,
            missing_socket=result.missing_socket,
        ),
        check_only=True,
    )


def _format_docker_revision_check(
    container_name: str,
    image: str,
    result: DockerImageCheckResult,
) -> str:
    current = format_image_version(
        result.current_image_id,
        result.current_image_created,
    )
    remote = format_image_version(
        result.remote_image_id or result.remote_digest,
        result.remote_image_created,
    )
    lines = [
        (
            f"Docker 镜像已是最新（与配置目标一致）：{container_name}"
            if result.up_to_date
            else f"配置目标与本机镜像不同：{container_name}"
        ),
        f"目标镜像：{image}",
        f"本机当前镜像ID：{current}",
        f"配置目标镜像ID：{remote}",
    ]
    if current_commit := visible_image_commit_summary(result.current_image_commit):
        lines.append(f"本机代码：{current_commit}")
    if remote_commit := visible_image_commit_summary(result.remote_image_commit):
        lines.append(f"目标代码：{remote_commit}")

    if result.github_main_repository:
        lines.append(f"GitHub 参考仓库：{result.github_main_repository}")
    if result.github_main_revision:
        lines.append(f"GitHub main：{_short_revision(result.github_main_revision)}")
        for label, revision in (
            ("目标代码", result.remote_image_revision),
            ("本机代码", result.current_image_revision),
        ):
            lines.append(
                _format_main_alignment(label, revision, result.github_main_revision)
            )
    else:
        lines.append(
            f"GitHub main 未确认：{result.github_main_error or '缺少源码元数据'}"
        )
    if not result.up_to_date:
        lines.append("操作：等待确认后更新并重启。")
    lines.append("本次只检查，未拉取镜像、未创建 Watchtower、未重启容器。")
    return "\n".join(lines)


def _short_revision(revision: str) -> str:
    return revision.strip()[:12] or "未知"


def _format_main_alignment(label: str, revision: str, main_revision: str) -> str:
    if not GIT_REVISION_PATTERN.fullmatch(revision.strip()):
        return f"{label}：缺少有效提交编号，无法比较 main。"
    if _revisions_match(revision, main_revision):
        return f"{label}已对齐 GitHub main。"
    return f"{label}（{_short_revision(revision)}）与参考 main 不同；未判断提交先后。"


def _revisions_match(left: str, right: str) -> bool:
    normalized_left = left.strip().lower()
    normalized_right = right.strip().lower()
    return bool(
        GIT_REVISION_PATTERN.fullmatch(normalized_left)
        and GIT_REVISION_PATTERN.fullmatch(normalized_right)
        and (
            normalized_left == normalized_right
            or normalized_left.startswith(normalized_right)
            or normalized_right.startswith(normalized_left)
        )
    )


def short_image_id(image_id: str) -> str:
    if not image_id:
        return "未知"
    return image_id.removeprefix("sha256:")[:12]


def format_image_version(image_id: str, created: str) -> str:
    short_id = short_image_id(image_id)
    created_text = format_docker_image_created(created)
    if not created_text:
        return short_id
    return f"{short_id}（{created_text}）"


def format_docker_image_created(created: str) -> str:
    if not created:
        return ""
    created = created.strip()
    match = DOCKER_TIMESTAMP_PATTERN.match(created)
    if match is not None:
        tz_text = match.group("tz") or ""
        if tz_text == "Z":
            tz_text = "+00:00"
        created = f"{match.group('head')}{tz_text}"
    try:
        value = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError:
        return created
    if value.tzinfo is None:
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S")


def visible_image_commit_summary(summary: str) -> str:
    stripped = summary.strip()
    if GIT_REVISION_PATTERN.fullmatch(stripped):
        return ""
    return stripped
