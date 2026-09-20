# SPDX-License-Identifier: MIT
"""OCI registry image references, authentication, and metadata lookups."""

from __future__ import annotations

import base64
import json
import re

import httpx

from ironsbot.services.operations.docker_models import (
    DockerImageInfo,
    DockerRegistryCredentials,
)

from .http import raise_for_docker_status

REGISTRY_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
REGISTRY_BEARER_PARAMETER = re.compile(r'(?P<key>[a-z]+)="(?P<value>[^"]*)"')
DOCKER_HUB_REGISTRIES = frozenset(
    ("docker.io", "index.docker.io", "registry-1.docker.io")
)


def split_docker_image(image: str) -> tuple[str, str]:
    last_segment = image.rsplit("/", maxsplit=1)[-1]
    if ":" not in last_segment:
        return image, "latest"
    repository, tag = image.rsplit(":", maxsplit=1)
    return repository, tag


def docker_registry_auth_headers(
    credentials: DockerRegistryCredentials | None,
) -> dict[str, str] | None:
    if credentials is None:
        return None
    if not credentials.username or not credentials.token:
        message = "private registry credentials are incomplete"
        raise TypeError(message)
    payload = json.dumps(
        {
            "username": credentials.username,
            "password": credentials.token,
            "serveraddress": "https://index.docker.io/v1/",
        },
        separators=(",", ":"),
    ).encode("utf-8")
    return {"X-Registry-Auth": base64.b64encode(payload).decode("ascii")}


async def inspect_remote_image_info(
    image: str,
    *,
    registry_credentials: DockerRegistryCredentials | None = None,
) -> DockerImageInfo:
    """Read remote OCI config metadata without pulling the image to Docker."""

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(10.0),
        follow_redirects=True,
    ) as client:
        return await inspect_registry_image_info(
            client,
            image,
            registry_credentials=registry_credentials,
        )


async def inspect_registry_image_info(
    client: httpx.AsyncClient,
    image: str,
    *,
    registry_credentials: DockerRegistryCredentials | None = None,
) -> DockerImageInfo:
    """Resolve an image config through the registry v2 manifest API."""

    registry_url, repository, reference = registry_image_reference(image)
    manifest_url = f"{registry_url}/v2/{repository}/manifests/{reference}"
    manifest = await registry_get_json(
        client,
        manifest_url,
        accept=REGISTRY_MANIFEST_ACCEPT,
        registry_credentials=registry_credentials,
    )
    if "manifests" in manifest:
        descriptor = linux_amd64_manifest_descriptor(manifest)
        digest = descriptor.get("digest")
        if not isinstance(digest, str) or not digest:
            message = "registry manifest index did not include an image digest"
            raise RuntimeError(message)
        manifest = await registry_get_json(
            client,
            f"{registry_url}/v2/{repository}/manifests/{digest}",
            accept=REGISTRY_MANIFEST_ACCEPT,
            registry_credentials=registry_credentials,
        )

    config = manifest.get("config")
    config_digest = config.get("digest") if isinstance(config, dict) else None
    if not isinstance(config_digest, str) or not config_digest:
        message = "registry image manifest did not include a config digest"
        raise RuntimeError(message)
    config_payload = await registry_get_json(
        client,
        f"{registry_url}/v2/{repository}/blobs/{config_digest}",
        registry_credentials=registry_credentials,
    )
    raw_config = config_payload.get("config")
    raw_labels = raw_config.get("Labels") if isinstance(raw_config, dict) else None
    labels = (
        {str(key): str(value) for key, value in raw_labels.items()}
        if isinstance(raw_labels, dict)
        else {}
    )
    created = config_payload.get("created")
    return DockerImageInfo(
        image_id=config_digest,
        created=created if isinstance(created, str) else "",
        labels=labels,
    )


def registry_image_reference(image: str) -> tuple[str, str, str]:
    repository, reference = split_docker_image(image)
    parts = repository.split("/")
    first = parts[0]
    has_explicit_registry = first == "localhost" or "." in first or ":" in first
    if not has_explicit_registry:
        path = repository if "/" in repository else f"library/{repository}"
        return "https://registry-1.docker.io", path, reference
    registry_path = "/".join(parts[1:])
    if not registry_path:
        message = f"Docker image does not include a repository path: {image}"
        raise ValueError(message)
    registry = (
        "registry-1.docker.io" if first.lower() in DOCKER_HUB_REGISTRIES else first
    )
    return f"https://{registry}", registry_path, reference


def linux_amd64_manifest_descriptor(manifest: dict[str, object]) -> dict[str, object]:
    descriptors = manifest.get("manifests")
    if not isinstance(descriptors, list):
        message = "registry manifest index did not include a manifest list"
        raise TypeError(message)
    candidates = [
        descriptor for descriptor in descriptors if isinstance(descriptor, dict)
    ]
    for descriptor in candidates:
        platform = descriptor.get("platform")
        if (
            isinstance(platform, dict)
            and platform.get("os") == "linux"
            and platform.get("architecture") == "amd64"
        ):
            return descriptor
    if candidates:
        return candidates[0]
    message = "registry manifest index did not include any image manifests"
    raise RuntimeError(message)


async def registry_get_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    accept: str | None = None,
    registry_credentials: DockerRegistryCredentials | None = None,
) -> dict[str, object]:
    headers = {} if accept is None else {"Accept": accept}
    response = await client.get(url, headers=headers)
    if response.status_code == httpx.codes.UNAUTHORIZED:
        response = await registry_get_with_bearer_token(
            client,
            response,
            url,
            headers=headers,
            registry_credentials=registry_credentials,
        )
    raise_for_docker_status(response)
    payload = response.json()
    if not isinstance(payload, dict):
        message = "registry did not return a JSON object"
        raise TypeError(message)
    return payload


async def registry_get_with_bearer_token(
    client: httpx.AsyncClient,
    challenge_response: httpx.Response,
    url: str,
    *,
    headers: dict[str, str],
    registry_credentials: DockerRegistryCredentials | None,
) -> httpx.Response:
    challenge = challenge_response.headers.get("WWW-Authenticate", "")
    if not challenge.lower().startswith("bearer "):
        raise_for_docker_status(challenge_response)
    parameters = {
        match.group("key"): match.group("value")
        for match in REGISTRY_BEARER_PARAMETER.finditer(challenge)
    }
    realm = parameters.pop("realm", "")
    if not realm:
        message = "registry bearer challenge did not include a token realm"
        raise RuntimeError(message)
    auth = (
        None
        if registry_credentials is None
        else httpx.BasicAuth(
            registry_credentials.username,
            registry_credentials.token,
        )
    )
    token_response = await client.get(realm, params=parameters, auth=auth)
    raise_for_docker_status(token_response)
    token_payload = token_response.json()
    token = (
        token_payload.get("token") or token_payload.get("access_token")
        if isinstance(token_payload, dict)
        else None
    )
    if not isinstance(token, str) or not token:
        message = "registry token endpoint did not return an access token"
        raise RuntimeError(message)
    return await client.get(
        url,
        headers={**headers, "Authorization": f"Bearer {token}"},
    )
