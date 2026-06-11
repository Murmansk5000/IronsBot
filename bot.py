# SPDX-License-Identifier: MIT
import nonebot

from ironsbot.app.bootstrap import bootstrap

_bootstrap_state = bootstrap()
driver = _bootstrap_state.driver
app = _bootstrap_state.app

if __name__ == "__main__":
    nonebot.run(host="127.0.0.1", port=8080, app=app)
