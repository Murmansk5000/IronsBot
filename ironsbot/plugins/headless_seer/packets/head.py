# SPDX-License-Identifier: GPL-3.0-or-later
from typing import Annotated

from ironsbot.integrations.headless_seer.packet.fields import Int, UInt, Unicode
from ironsbot.integrations.headless_seer.packet.packet import Deserializable
from ironsbot.integrations.headless_seer.type_hint import CommandID


class HeadInfo(Deserializable):
    version: Annotated[str, Unicode[1]]
    cmd_id: Annotated[CommandID, UInt]
    user_id: UInt
    result: Int
