from contextlib import suppress
from typing import Any

from hishel.httpx import AsyncCacheClient
from httpx import HTTPStatusError
from typing_extensions import Self

from ..backend import DirectoryListing, FileEntry

_API_BASE = "https://api.cnb.cool"


class CnbBackend:
    """CNB OpenAPI 客户端。

    复用单个 ``httpx.AsyncClient`` 以利用连接池。
    支持作为异步上下文管理器使用，也可手动调用 :meth:`aclose` 释放资源。

    Parameters
    ----------
    token : str
        访问令牌（Bearer Token）。
    repo : str
        仓库标识符，格式：``组织名称/仓库名称``。
    """

    def __init__(self, token: str, *, repo: str) -> None:
        self._repo = repo
        self._client = AsyncCacheClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.cnb.api+json",
            },
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.aclose()

    def _url(self, path: str) -> str:
        return f"{_API_BASE}/{path}"

    async def count(self, path: str = "") -> int:
        """获取目录下的文件数量（仅请求条目数，不解析内容）。"""

        # 先获取目录下的count文件，如果存在则直接返回
        with suppress(HTTPStatusError):
            count = await self.get_file(f"{path}/count")
            return int(count)

        # 如果不存在则通过list_dir获取
        listing = await self.list_dir(path)
        return listing.count

    async def list_dir(
        self,
        path: str = "",
        *,
        ref: str | None = None,
    ) -> DirectoryListing:
        """获取指定目录下所有文件信息和文件数量。

        Parameters
        ----------
        path : str
            目录路径，空字符串表示仓库根目录。
        ref : str | None
            分支名或提交哈希，``None`` 表示默认分支。
        """
        endpoint = f"{self._repo}/-/git/contents/{path or ''}"

        params: dict[str, str] = {}
        if ref is not None:
            params["ref"] = ref

        resp = await self._client.get(
            self._url(endpoint),
            params=params,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        entries = [
            FileEntry(
                name=e["name"],
                path=e["path"],
            )
            for e in (data.get("entries") or [])
        ]
        return DirectoryListing(entries=entries, count=len(entries))

    async def get_file(
        self,
        file_path: str,
        *,
        ref: str | None = None,
    ) -> bytes:
        """获取单个文件内容，支持 LFS 文件。

        对于普通 blob 文件，直接解码 base64 内容返回；
        对于 LFS 文件，优先使用 ``lfs_download_url`` 下载，
        若该字段为空则回退到 ``/{repo}/-/lfs/{oid}`` 接口获取预签名链接后下载。

        Parameters
        ----------
        file_path : str
            文件路径。
        ref : str | None
            分支名或提交哈希，``None`` 表示默认分支。
        """
        url = self._url(f"{self._repo}/-/git/contents/{file_path}")

        params: dict[str, str] = {}
        if ref is not None:
            params["ref"] = ref

        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()

        content_type = data.get("type")

        if content_type == "lfs":
            return await self._download_lfs(data)

        if content_type == "blob":
            return await self._download_blob(data)

        msg = f"不支持的内容类型: {content_type}"
        raise ValueError(msg)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    async def _download_lfs(self, data: dict[str, Any]) -> bytes:
        lfs_url: str | None = data.get("lfs_download_url")
        if not lfs_url:
            lfs_url = await self._resolve_lfs_url(
                oid=data["lfs_oid"],
                name=data["name"],
            )
        resp = await self._client.get(lfs_url)
        resp.raise_for_status()
        return resp.content

    async def _download_blob(self, data: dict[str, Any]) -> bytes:
        url = self._url(f"{self._repo}/-/git/raw/main/{data['path']}")
        resp = await self._client.get(url)
        resp.raise_for_status()
        return resp.content

    async def _resolve_lfs_url(self, *, oid: str, name: str) -> str:
        """通过 ``/{repo}/-/lfs/{oid}`` 接口获取预签名下载链接。"""
        url = self._url(f"{self._repo}/-/lfs/{oid}")
        resp = await self._client.get(
            url,
            params={"name": name},
            follow_redirects=False,
        )
        if resp.is_redirect:
            location = resp.headers.get("location", "")
            if location:
                return location
        resp.raise_for_status()
        return str(resp.url)
