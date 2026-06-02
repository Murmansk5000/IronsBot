"""图床后端协议定义。

提供统一的图床后端抽象，使插件能够兼容不同的图床实现（CNB、GitHub、S3 等）。
"""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from typing_extensions import Self


@dataclass(frozen=True, slots=True)
class FileEntry:
    """目录中的单个文件/子目录条目。"""

    name: str
    path: str


@dataclass(frozen=True, slots=True)
class DirectoryListing:
    """目录列表结果。"""

    entries: list[FileEntry]
    count: int


@runtime_checkable
class ImageBackend(Protocol):
    """图床后端协议。

    所有图床实现（CNB、GitHub、本地文件系统等）都应满足此协议。
    支持作为异步上下文管理器使用。
    """

    async def count(self, path: str = "") -> int:
        """获取目录下的文件数量。

        Parameters
        ----------
        path : str
            目录路径，空字符串表示根目录。

        Returns
        -------
        int
            目录中的条目数量。
        """
        ...

    async def get_file(self, file_path: str) -> bytes:
        """获取指定路径的文件内容。

        Parameters
        ----------
        file_path : str
            文件在后端中的相对路径。

        Returns
        -------
        bytes
            文件的原始二进制内容。
        """
        ...

    async def list_dir(self, path: str = "") -> DirectoryListing:
        """列出目录下所有条目。

        Parameters
        ----------
        path : str
            目录路径，空字符串表示根目录。

        Returns
        -------
        DirectoryListing
            包含条目列表和数量的目录信息。
        """
        ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None: ...
