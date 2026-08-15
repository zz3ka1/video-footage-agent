from video_footage_agent.media import format_time


def test_format_time_uses_minutes_for_short_media() -> None:
    assert format_time(0) == "00:00"
    assert format_time(65.2) == "01:05"
    assert format_time(3599.6) == "01:00:00"


def test_format_time_uses_hours_when_needed() -> None:
    assert format_time(3661) == "01:01:01"
    assert format_time(61, include_hours=True) == "00:01:01"
