# SPDX-License-Identifier: GPL-3.0-or-later
"""Wire position bounds are independent of display and search budgets."""

MAX_RANK_INDEX = (1 << 32) - 1
MAX_RANK_POSITION = MAX_RANK_INDEX + 1
MAX_LOCAL_RANK_POSITION = (1 << 63) - 1


class RankRangeError(ValueError):
    """A rank interval cannot be represented without changing its meaning."""

    def __init__(
        self, start_rank: int, end_rank: int, maximum: int = MAX_RANK_POSITION
    ) -> None:
        super().__init__(
            f"榜单范围无效：第 {start_rank}-{end_rank} 名。"
            f"起点须大于零、终点不得小于起点，整数边界允许最大名次为 {maximum}。"
        )


def validate_rank_interval(
    start_rank: int, end_rank: int, *, maximum: int = MAX_RANK_POSITION
) -> None:
    if not 1 <= start_rank <= end_rank <= maximum:
        raise RankRangeError(start_rank, end_rank, maximum)


def validate_rank_offsets(start: int, end: int) -> None:
    validate_rank_interval(start + 1, end + 1)


def range_failure(start_rank: int, end_rank: int, error: Exception) -> str:
    reason = "查询超时" if isinstance(error, TimeoutError) else "协议请求或数据解析失败"
    return (
        f"❌请求区间：第 {start_rank}-{end_rank} 名。{reason}，未全部完成。"
        "已取得的完整页缓存保留；实际完成条数尚未确认，不据此判断未上榜或协议上限。"
    )


def range_completion(
    start_rank: int,
    requested_count: int,
    execution_count: int,
    returned_count: int,
    *,
    incomplete_reason: str = "服务端返回空页或短页。",
) -> str:
    lines = [
        f"请求区间：第 {start_rank}-{start_rank + requested_count - 1} 名",
        f"执行区间：第 {start_rank}-{start_rank + execution_count - 1} 名",
        f"实际返回：{returned_count}/{requested_count} 条",
    ]
    if execution_count < requested_count:
        lines.append(f"数量预算：本次最多处理 {execution_count} 条，剩余区间未请求。")
    if returned_count < execution_count:
        lines.append(incomplete_reason + "未返回的位置不能据此认定为协议上限。")
    return "\n".join(lines)
