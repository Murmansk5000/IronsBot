# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import quote, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from anyio import Path as AsyncPath
from nonebot import logger

LOCAL_TZ = ZoneInfo("Asia/Shanghai")
GITHUB_REPO_PATH_PARTS = 2
RESTART_CONTAINER_STOP_TIMEOUT_SECONDS = 3
GIT_REVISION_PATTERN = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
DOCKER_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<head>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.\d+)?"
    r"(?P<tz>Z|[+-]\d{2}:\d{2})?$"
)


@dataclass(frozen=True, slots=True)
class DockerImageInfo:
    image_id: str
    created: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WatchtowerUpdateOptions:
    image: str
    docker_api_version: str


@dataclass(frozen=True, slots=True)
class DockerUpdateResult:
    ok: bool
    message: str = ""
    updater_container_id: str = ""
    up_to_date: bool = False
    current_image_id: str = ""
    current_image_created: str = ""
    current_image_commit: str = ""
    target_image_id: str = ""
    target_image_created: str = ""
    target_image_commit: str = ""
    missing_socket: bool = False


def format_docker_update_reply(
    *,
    container_name: str,
    image: str,
    result: DockerUpdateResult,
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
        return "\n".join(lines)

    if result.ok:
        current_commit = visible_image_commit_summary(result.current_image_commit)
        target_commit = visible_image_commit_summary(result.target_image_commit)
        lines = [
            f"检测到新镜像，Docker 自更新任务已启动：{container_name}",
            f"目标镜像：{image}",
            f"当前镜像ID：{current_version}",
            f"最新镜像ID：{target_version}",
        ]
        if current_commit:
            lines.append(f"当前代码：{current_commit}")
        if target_commit:
            lines.append(f"最新代码：{target_commit}")
        lines.extend(
            [
                "接下来 Watchtower 会拉取最新镜像并重建当前容器，"
                "机器人可能会短暂离线；重启后才算真正使用新镜像。",
            ]
        )
        return "\n".join(lines)

    return (
        f"Docker 镜像检查失败：{container_name}\n"
        f"目标镜像：{image}\n"
        f"错误：{result.message or '未知错误'}"
    ).rstrip()


def is_docker_update_started(result: DockerUpdateResult) -> bool:
    return bool(result.ok and not result.up_to_date and result.updater_container_id)


def resolve_docker_container_name(configured_name: str) -> str:
    return os.getenv("HOST_CONTAINERNAME", "").strip() or configured_name


def split_docker_image(image: str) -> tuple[str, str]:
    last_segment = image.rsplit("/", maxsplit=1)[-1]
    if ":" not in last_segment:
        return image, "latest"
    repository, tag = image.rsplit(":", maxsplit=1)
    return repository, tag


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


def github_repo_from_image_labels(labels: dict[str, str]) -> tuple[str, str] | None:
    source = labels.get("org.opencontainers.image.source", "").strip()
    if not source:
        return None
    parsed = urlparse(source)
    if parsed.netloc.lower() != "github.com":
        return None
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < GITHUB_REPO_PATH_PARTS:
        return None
    repo = parts[1].removesuffix(".git")
    if not parts[0] or not repo:
        return None
    return parts[0], repo


async def restart_docker_container(
    *,
    container_name: str,
    socket_path: str,
    timeout_seconds: float,
) -> None:
    if not await AsyncPath(socket_path).exists():
        msg = f"Docker socket not found: {socket_path}"
        raise RuntimeError(msg)

    logger.warning("admin requested docker container restart: {}", container_name)
    transport = httpx.AsyncHTTPTransport(uds=socket_path)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://docker",
        timeout=httpx.Timeout(timeout_seconds),
    ) as client:
        response = await client.post(
            f"/containers/{quote(container_name, safe='')}/restart",
            params={"t": RESTART_CONTAINER_STOP_TIMEOUT_SECONDS},
        )
        response.raise_for_status()


async def start_watchtower_update(
    *,
    container_name: str,
    image: str,
    socket_path: str,
    watchtower: WatchtowerUpdateOptions,
    timeout_seconds: float,
) -> DockerUpdateResult:
    logger.warning(
        "admin requested docker self update: container={}, watchtower={}",
        container_name,
        watchtower.image,
    )
    if not await AsyncPath(socket_path).exists():
        logger.warning("docker self update failed: socket not found: {}", socket_path)
        return DockerUpdateResult(
            ok=False,
            missing_socket=True,
            message=f"Docker socket not found: {socket_path}",
        )

    transport = httpx.AsyncHTTPTransport(uds=socket_path)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://docker",
            timeout=httpx.Timeout(timeout_seconds),
        ) as client:
            current_image_id = await inspect_container_image_id(
                client,
                container_name,
            )
            current_image_info = await inspect_image_info(client, current_image_id)
            target_image_info = await pull_docker_image(client, image)
            current_commit = await resolve_image_commit_summary(
                current_image_info,
                fallback_repo=("Murmansk5000", "IronsBot"),
            )
            target_commit = await resolve_image_commit_summary(
                target_image_info,
                fallback_repo=("Murmansk5000", "IronsBot"),
            )
            if current_image_info.image_id == target_image_info.image_id:
                return DockerUpdateResult(
                    ok=True,
                    up_to_date=True,
                    current_image_id=current_image_info.image_id,
                    current_image_created=current_image_info.created,
                    current_image_commit=current_commit,
                    target_image_id=target_image_info.image_id,
                    target_image_created=target_image_info.created,
                    target_image_commit=target_commit,
                )

            await pull_docker_image(client, watchtower.image)
            updater_id = await create_watchtower_container(
                client,
                container_name=container_name,
                socket_path=socket_path,
                watchtower=watchtower,
            )
            response = await client.post(f"/containers/{updater_id}/start")
            response.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.opt(exception=True).warning("docker self update failed")
        return DockerUpdateResult(ok=False, message=str(e))

    return DockerUpdateResult(
        ok=True,
        updater_container_id=updater_id,
        current_image_id=current_image_info.image_id,
        current_image_created=current_image_info.created,
        current_image_commit=current_commit,
        target_image_id=target_image_info.image_id,
        target_image_created=target_image_info.created,
        target_image_commit=target_commit,
    )


async def inspect_container_image_id(
    client: httpx.AsyncClient,
    container_name: str,
) -> str:
    response = await client.get(f"/containers/{quote(container_name, safe='')}/json")
    response.raise_for_status()
    data = response.json()
    image_id = data.get("Image")
    if not isinstance(image_id, str) or not image_id:
        msg = "Docker API did not return current container image id"
        raise RuntimeError(msg)
    return image_id


async def pull_docker_image(
    client: httpx.AsyncClient,
    image: str,
) -> DockerImageInfo:
    repository, tag = split_docker_image(image)
    response = await client.post(
        "/images/create",
        params={"fromImage": repository, "tag": tag},
    )
    response.raise_for_status()
    return await inspect_image_info(client, image)


async def inspect_image_info(client: httpx.AsyncClient, image: str) -> DockerImageInfo:
    response = await client.get(f"/images/{quote(image, safe='')}/json")
    response.raise_for_status()
    data = response.json()
    image_id = data.get("Id")
    if not isinstance(image_id, str) or not image_id:
        msg = "Docker API did not return target image id"
        raise RuntimeError(msg)
    created = data.get("Created")
    raw_labels = {}
    config = data.get("Config")
    if isinstance(config, dict):
        labels = config.get("Labels")
        if isinstance(labels, dict):
            raw_labels = {
                str(key): str(value)
                for key, value in labels.items()
                if value is not None
            }
    return DockerImageInfo(
        image_id=image_id,
        created=created if isinstance(created, str) else "",
        labels=raw_labels,
    )


async def resolve_image_commit_summary(
    image_info: DockerImageInfo,
    *,
    fallback_repo: tuple[str, str] | None = None,
) -> str:
    revision = image_info.labels.get("org.opencontainers.image.revision", "").strip()
    if not revision:
        return ""

    short_revision = revision[:12]
    repo = github_repo_from_image_labels(image_info.labels) or fallback_repo
    if repo is not None:
        owner, name = repo
        try:
            async with httpx.AsyncClient(
                timeout=8.0,
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    f"https://api.github.com/repos/{owner}/{name}/commits/{revision}",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "User-Agent": "IronsBot-DockerUpdate",
                    },
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "failed to fetch docker image commit message: "
                "repo={}/{} revision={} error={}",
                owner,
                name,
                short_revision,
                e,
            )
        else:
            commit = data.get("commit")
            if isinstance(commit, dict):
                message = commit.get("message")
                if isinstance(message, str):
                    first_line = (
                        message.strip().splitlines()[0].strip()
                        if message.strip()
                        else ""
                    )
                    if first_line:
                        return f"{short_revision} {first_line}"
    return ""


async def create_watchtower_container(
    client: httpx.AsyncClient,
    *,
    container_name: str,
    socket_path: str,
    watchtower: WatchtowerUpdateOptions,
) -> str:
    updater_name = f"ironsbot-watchtower-once-{uuid4().hex[:12]}"
    response = await client.post(
        "/containers/create",
        params={"name": updater_name},
        json={
            "Image": watchtower.image,
            "Cmd": ["--run-once", "--cleanup", container_name],
            "Env": [f"DOCKER_API_VERSION={watchtower.docker_api_version}"],
            "HostConfig": {
                "AutoRemove": True,
                "Binds": [f"{socket_path}:/var/run/docker.sock"],
            },
        },
    )
    response.raise_for_status()
    data = response.json()
    container_id = data.get("Id")
    if not isinstance(container_id, str) or not container_id:
        msg = "Docker API did not return updater container id"
        raise RuntimeError(msg)
    return container_id
