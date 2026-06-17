from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class InvalidImageArgumentError(Exception):
    """Raised when the image command argument is neither empty nor numeric."""


class ImageIndexOutOfRangeError(Exception):
    def __init__(self, max_index: int) -> None:
        self.max_index = max_index
        super().__init__(f"编号必须在1到{max_index}之间！")


@dataclass(frozen=True, slots=True)
class ImageSelection:
    index: int
    is_random: bool

    @property
    def random_text(self) -> str:
        return "随机" if self.is_random else "自选"


def select_image(
    arg_text: str,
    max_index: int,
    *,
    random_index_factory: "Callable[[], int] | None" = None,
) -> ImageSelection:
    if arg_text.isdigit():
        selection = ImageSelection(index=int(arg_text), is_random=False)
    elif not arg_text:
        if random_index_factory is None:
            index = random.randint(1, max_index)
        else:
            index = random_index_factory()
        selection = ImageSelection(index=index, is_random=True)
    else:
        raise InvalidImageArgumentError

    if not 1 <= selection.index <= max_index:
        raise ImageIndexOutOfRangeError(max_index)

    return selection


def build_image_file_path(
    image_dir: str,
    image_filename_template: str,
    index: int,
) -> str:
    return "/".join(
        [image_dir, image_filename_template.format(index=index)]
    )
