from video_footage_agent.triage import TriageConfig, group_windows


def metric(
    second: int,
    brightness: float = 100.0,
    sharpness: float = 50.0,
    change: float = 10.0,
) -> dict:
    return {
        "second": second,
        "brightness": brightness,
        "sharpness": sharpness,
        "dark_ratio": 0.0,
        "bright_ratio": 0.0,
        "frame_change": change,
    }


def test_config_validation() -> None:
    TriageConfig().validate()


def test_group_windows_marks_dark_window_as_candidate() -> None:
    rows = [
        metric(second, brightness=5.0) | {"dark_ratio": 0.9} for second in range(10)
    ]
    windows = group_windows(rows, 10, window_seconds=10)
    assert windows[0]["technical_status"] == "TECHNICAL_FAIL_CANDIDATE"
    assert "very_dark" in windows[0]["flags"]


def test_group_windows_does_not_treat_motion_as_failure() -> None:
    rows = [metric(second, change=60.0) for second in range(10)]
    windows = group_windows(rows, 10, window_seconds=10)
    assert windows[0]["technical_status"] == "REVIEW"
    assert "large_visual_change" in windows[0]["flags"]
