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
    assert (
        parser.parse_args(
            [
                "film-insights-validate",
                "human_insights.md",
                "--scene-map",
                "scene_map.csv",
            ]
        ).command
        == "film-insights-validate"
    )
    assert (
        parser.parse_args(
            [
                "film-draft",
                "movie_FULL_project.json",
                "--output",
                "draft-package",
                "--verify-source-hash",
            ]
        ).command
        == "film-draft"
    )
    generated = parser.parse_args(
        [
            "film-generate",
            "draft-package",
            "--output",
            "generated",
            "--model",
            "explicit-model",
            "--reasoning-effort",
            "high",
            "--verbosity",
            "high",
            "--max-output-tokens",
            "5000",
        ]
    )
    assert generated.command == "film-generate"
    assert generated.model == "explicit-model"
    assert generated.max_output_tokens == 5000
