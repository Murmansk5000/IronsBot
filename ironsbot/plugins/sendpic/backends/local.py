"""本地文件系统图床后端。"""

from pathlib import Path

from typing_extensions import Self

from ..backend import DirectoryListing, FileEntry


class LocalBackend:
    """基于本地文件系统的图床后端实现。

    Parameters
    ----------
    root : str | Path
        图片根目录的路径，所有文件操作都相对于此目录。
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    async def count(self, path: str = "") -> int:
        """获取目录下的文件数量。"""
        target = self._root / path if path else self._root
        self._ensure_within_root(target)
        return sum(1 for _ in target.iterdir())

    async def get_file(self, file_path: str) -> bytes:
        """读取指定路径的文件内容。"""
        target = self._root / file_path
        self._ensure_within_root(target)
        return target.read_bytes()

    async def list_dir(self, path: str = "") -> DirectoryListing:
        """列出目录下所有条目。"""
        target = self._root / path if path else self._root
        self._ensure_within_root(target)

        entries = [
            FileEntry(
                name=item.name,
                path=str(item.relative_to(self._root)),
            )
            for item in sorted(target.iterdir())
        ]
        return DirectoryListing(entries=entries, count=len(entries))

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        pass

    def _ensure_within_root(self, target: Path) -> None:
        """确保目标路径不会逃逸出根目录。"""
        resolved = target.resolve()
        if not resolved.is_relative_to(self._root):
            msg = f"路径 {target} 不在允许的根目录内"
            raise ValueError(msg)
