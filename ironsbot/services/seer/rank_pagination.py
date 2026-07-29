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
    starts = [page_start]
    for distance in range(1, window_pages + 1):
        previous = page_start - distance * page_size
        following = page_start + distance * page_size
        if previous >= 0:
            starts.append(previous)
        starts.append(following)
    return starts
