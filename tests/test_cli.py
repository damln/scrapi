import pytest

from app.cli import build_parser


def test_main_help_is_an_agent_discoverable_cli_guide():
    help_text = build_parser().format_help()

    for command in ("content", "asset", "export", "actions", "status", "agent"):
        assert command in help_text

    for detail in (
        "without starting the HTTP server",
        "SCRAPI_API_TOKEN is not required",
        "python -m app.cli content https://example.com --format markdown",
        "python -m app.cli COMMAND --help",
        "python -m app.cli agent > scrapi-api.md",
        "FIRECRAWL_API_KEY",
        "PROXY_URL",
        "BROWSER_MAX_CONCURRENT",
        "Twitter/X and YouTube",
        "docker run --rm scrapi",
        "output behavior:",
    ):
        assert detail in help_text


@pytest.mark.parametrize(
    ("command", "expected_details"),
    [
        ("content", ("--provider-order", "--proxy-profile", "--format", "examples:")),
        ("asset", ("--output-format", "--max-width", "base64-encoded data", "examples:")),
        ("export", ("--url", "--html-file", "--request", "binary stdout", "examples:")),
        ("actions", ("--request", "read JSON from stdin", "agent command", "examples:")),
        ("status", ("--proxy-profile", "JSON report", "examples:")),
        ("agent", ("Pydantic models", "scrapi-api.md", "examples:")),
    ],
)
def test_subcommand_help_explains_options_and_examples(command, expected_details, capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args([command, "--help"])

    assert exc_info.value.code == 0
    help_text = capsys.readouterr().out
    for detail in expected_details:
        assert detail in help_text
