import pytest

from ironsbot.plugins.server_status import (
    DockerUpdateResult,
    _format_docker_update_reply,
    _resolve_docker_container_name,
    _split_docker_image,
)


def test_split_docker_image_with_tag() -> None:
    assert _split_docker_image("containrrr/watchtower:latest") == (
        "containrrr/watchtower",
        "latest",
    )


def test_split_docker_image_defaults_latest() -> None:
    assert _split_docker_image("containrrr/watchtower") == (
        "containrrr/watchtower",
        "latest",
    )


def test_resolve_container_name_prefers_unraid_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOST_CONTAINERNAME", "ironsbot-prod")

    assert _resolve_docker_container_name("ironsbot") == "ironsbot-prod"


def test_format_docker_update_missing_socket_reply() -> None:
    reply = _format_docker_update_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerUpdateResult(ok=False, missing_socket=True),
    )

    assert "Docker socket" in reply
    assert "/更新镜像" in reply


def test_format_docker_update_success_reply() -> None:
    reply = _format_docker_update_reply(
        container_name="ironsbot",
        image="murmansk5000/ironsbot:latest",
        result=DockerUpdateResult(
            ok=True,
            updater_container_id="1234567890abcdef",
        ),
    )

    assert "Docker 自更新任务已启动" in reply
    assert "murmansk5000/ironsbot:latest" in reply
    assert "1234567890ab" in reply
