from ironsbot.services.messaging.meeting import build_meeting_reply


def test_build_meeting_reply_returns_none_without_number() -> None:
    assert build_meeting_reply("", "{meeting_number}") is None


def test_build_meeting_reply_formats_tencent_meeting_number() -> None:
    reply = build_meeting_reply(
        "6638682008",
        (
            "会议号：{meeting_number}\n"
            "数字：{meeting_digits}\n"
            "链接：{meeting_url}"
        ),
    )

    assert reply == (
        "会议号：663-868-2008\n"
        "数字：6638682008\n"
        "链接：https://meeting.tencent.com/p/6638682008"
    )
