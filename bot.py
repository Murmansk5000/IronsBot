# SPDX-License-Identifier: MIT
import nonebot

from ironsbot.app.bootstrap import bootstrap

_bootstrap_state = bootstrap()
driver = _bootstrap_state.driver
app = _bootstrap_state.app

if __name__ == "__main__":
    nonebot.run(app=app)
