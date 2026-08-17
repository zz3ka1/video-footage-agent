from video_footage_agent.cli import build_parser


def test_parser_supports_main_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["doctor"]).command == "doctor"
    assert (
        parser.parse_args(["inventory", ".", "--output", "inventory.csv"]).command
        == "inventory"
    )
    assert (
        parser.parse_args(["triage", "clip.mp4", "--output", "out"]).command == "triage"
    )
    assert (
        parser.parse_args(
            ["consolidate", "inventory.csv", "target", "--dry-run"]
        ).dry_run
        is True
    )
    assert (
        parser.parse_args(
            [
                "film-init",
                "--output",
                "film-project",
                "--project-id",
                "movie_demo",
                "--title",
                "示例电影",
                "--original-title",
                "Example Film",
                "--release-year",
                "2000",
            ]
        ).command
        == "film-init"
    )
