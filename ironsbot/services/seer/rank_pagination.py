# SPDX-License-Identifier: GPL-3.0-or-later


def rank_page_size(configured: int) -> int:
    return max(1, min(configured, 100))


def rank_page_start(index: int, *, page_size: int) -> int:
    return max(0, index) // page_size * page_size


def rank_window_page_starts(
    *,
    center_index: int,
    page_size: int,
    window_pages: int,
) -> list[int]:
    page_start = center_index // page_size * page_size
    first_page_start = max(0, page_start - window_pages * page_size)
    last_page_start = page_start + window_pages * page_size
    return list(range(first_page_start, last_page_start + 1, page_size))
