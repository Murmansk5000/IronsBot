# SPDX-License-Identifier: GPL-3.0-or-later
from nonebot.params import Depends
from pydantic import Field

from ironsbot.utils.parse_arg import ValidatedIntArg

TeamIdValidator = ValidatedIntArg(
    Field(ge=100000, le=200_000_000_0),
    "❌ 战队ID范围必须在 100000~2000000000 之间！",
)


PlayerIdValidator = ValidatedIntArg(
    Field(ge=50000, le=200_000_000_0),
    "❌ 米米号无效，请输入 50000 ~ 2000000000 之间的数字",
)


TeamIdArg = Depends(TeamIdValidator)
PlayerIdArg = Depends(PlayerIdValidator)
