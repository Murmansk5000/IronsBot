from ironsbot.app.command_directory.dynamic import configured_message_commands
from ironsbot.config.models.messaging import MessageConfig, MessageScheduledAction


def test_message_schedule_is_documented_as_automatic_not_a_command() -> None:
    commands = configured_message_commands(
        MessageConfig(
            schedules=[
                MessageScheduledAction(
                    id="daily_reminder",
                    name="每日签到提醒",
                    feature="custom_reminder",
                    messages=["提醒内容"],
                    time="23:05",
                )
            ]
        )
    )

    schedule = next(
        command
        for command in commands
        if command.id == "messaging.schedule.daily_reminder"
    )
    assert schedule.examples == ("每日签到提醒（每天 23:05:00）",)
    assert schedule.description == "按配置时间自动发送推送内容"
    assert schedule.features_any == ("custom_reminder",)
    assert schedule.interaction == "automatic"
