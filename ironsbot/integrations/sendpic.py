# SPDX-License-Identifier: MIT
from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

from anyio import Path as AsyncPath
from httpx import HTTPStatusError, Response

if TYPE_CHECKING:
    from httpx import AsyncClient

    from ironsbot.services.messaging.sendpic import ImageBackend

API_BASE = "https://api.cnb.cool"
CNB_CONFIG_REQUIRED_ERROR = "启用 CNB 图床时必须配置 token 和 cnb_repo"
FIXED_IMAGE_ROOT = Path(__file__).resolve().parent / "assets" / "sendpic"


class SendpicBackendProvider:
    def __init__(
        self,
        client: AsyncClient,
        *,
        cnb_token: str | None,
        cnb_repo: str | None,
        local_root: Path,
    ) -> None:
        self._client = client
        self._token = cnb_token
        self._repo = cnb_repo
        self._local = LocalBackend(local_root)
        self._fixed = LocalBackend(FIXED_IMAGE_ROOT)

    def __call__(self, kind: str) -> ImageBackend:
        if kind == "fixed":
            return self._fixed
        if kind == "local":
            return self._local
        if kind == "cnb" and self._token and self._repo:
            return CnbBackend(
                self._client,
                token=self._token,
                repo=self._repo,
            )
        if kind == "cnb":
            raise ValueError(CNB_CONFIG_REQUIRED_ERROR)
        raise ValueError(f"不支持的图床类型：{kind}")


class LocalBackend:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    async def count(self, path: str = "") -> int:
        count = 0
        async for _ in AsyncPath(self._resolve(path)).iterdir():
            count += 1
        return count

    async def get_file(self, file_path: str) -> bytes:
        return await AsyncPath(self._resolve(file_path)).read_bytes()

    def _resolve(self, path: str) -> Path:
        target = (self._root / path).resolve()
        if not target.is_relative_to(self._root):
            message = f"路径 {target} 不在允许的根目录内"
            raise ValueError(message)
        return target


class CnbBackend:
    def __init__(
        self,
        client: AsyncClient,
        *,
        token: str,
        repo: str,
    ) -> None:
        self._client = client
        self._repo = repo
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.cnb.api+json",
        }

    async def count(self, path: str = "") -> int:
        with suppress(HTTPStatusError):
            return int(await self.get_file(f"{path}/count"))
        return await self._list_count(path)

    async def get_file(
        self,
        file_path: str,
        *,
        ref: str | None = None,
    ) -> bytes:
        response = await self._get(
            f"{self._repo}/-/git/contents/{file_path}",
            params={"ref": ref} if ref else None,
        )
        data: dict[str, Any] = response.json()
        if data.get("type") == "lfs":
            return await self._download_lfs(data)
        if data.get("type") == "blob":
            path = f"{self._repo}/-/git/raw/main/{data['path']}"
            return (await self._get(path)).content
        message = f"不支持的内容类型: {data.get('type')}"
        raise ValueError(message)

    async def _list_count(self, path: str) -> int:
        response = await self._get(f"{self._repo}/-/git/contents/{path}")
        data: dict[str, Any] = response.json()
        return len(data.get("entries") or ())

    async def _download_lfs(self, data: dict[str, Any]) -> bytes:
        url = data.get("lfs_download_url") or await self._resolve_lfs_url(
            oid=data["lfs_oid"],
            name=data["name"],
        )
        response = await self._client.get(url, follow_redirects=True)
        response.raise_for_status()
        return response.content

    async def _resolve_lfs_url(self, *, oid: str, name: str) -> str:
        response = await self._client.get(
            f"{API_BASE}/{self._repo}/-/lfs/{oid}",
            headers=self._headers,
            params={"name": name},
            follow_redirects=False,
        )
        if response.is_redirect:
            location = response.headers.get("location")
            if location:
                return location
        response.raise_for_status()
        return str(response.url)

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        follow_redirects: bool = True,
    ) -> Response:
        response = await self._client.get(
            f"{API_BASE}/{path}",
            headers=self._headers,
            params=params,
            follow_redirects=follow_redirects,
        )
        response.raise_for_status()
        return response
