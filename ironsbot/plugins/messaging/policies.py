from ironsbot.plugins.admin_priority import wait_for_superuser_priority
from ironsbot.shared.messaging import configure_reply_delivery_policy

_policy_state = {"registered": False}


def setup_messaging_delivery_policies() -> None:
    if _policy_state["registered"]:
        return

    configure_reply_delivery_policy(
        before_send=wait_for_superuser_priority,
    )
    _policy_state["registered"] = True
