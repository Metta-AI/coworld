from pathlib import Path

from typer.testing import CliRunner

from coworld.cli import app

COOKBOOK = Path(__file__).resolve().parents[1] / "COOKBOOK.md"
RUNNER = CliRunner()


def test_cookbook_answers_cli_faqs() -> None:
    text = COOKBOOK.read_text(encoding="utf-8")

    required_phrases = [
        "## FAQ",
        "### How do I play a game locally?",
        "uv run coworld play",
        "uv run coworld run-episode",
        "--variant",
        "### How do I run hosted non-tournament checks?",
        "uv run coworld hosted-game create",
        "uv run coworld xp-request create",
        "roster",
        "### How do I submit a policy to the Observatory?",
        "uv run coworld upload-policy",
        "uv run coworld submit",
        "--use-bedrock",
        "--secret-env",
        "### How do I know my policy passed self-play?",
        "coworld xp-request episodes",
        "### How do I get logs, replays, and debugging files after an episode?",
        "uv run coworld episode-logs",
        "--artifact",
        "uv run coworld replay-open",
        "error_type",
        "### How do I build an agent policy?",
        "COWORLD_PLAYER_WS_URL",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_cookbook_faq_commands_match_cli_help() -> None:
    command_help_checks = {
        ("play",): ["--variant", "--use-bedrock", "--secret-env", "--run"],
        ("run-episode",): ["--episodes", "--variant", "--use-bedrock", "--secret-env", "--run"],
        ("scrimmage",): ["--variant"],
        ("hosted-game",): ["create", "join"],
        ("hosted-game", "create"): ["--variant"],
        ("hosted-game", "join"): [],
        ("xp-request", "create"): [],
        ("xp-request", "episodes"): [],
        ("upload-policy",): ["--name", "--run", "--use-bedrock", "--secret-env"],
        ("submit",): ["--league"],
        ("replay",): [],
        ("episodes",): ["--json"],
        ("episode-logs",): ["--game", "--agent", "--mine", "--artifact", "--download-dir"],
        ("replay-open",): ["--hosted"],
    }

    for command, expected_options in command_help_checks.items():
        result = RUNNER.invoke(app, [*command, "--help"], color=False)

        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output
        for command_part in command:
            assert command_part in result.output
        for expected_option in expected_options:
            assert expected_option in result.output
