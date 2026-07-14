from pathlib import Path

import pytest
import typer

from coworld.cli_support import active_docker_context, observatory_web_url, validate_run_argv


def test_active_docker_context_reads_docker_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "config.json").write_text('{"currentContext":"orbstack"}\n', encoding="utf-8")
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path))
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)

    assert active_docker_context() == "orbstack"


def test_active_docker_context_identifies_docker_host_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOCKER_CONTEXT", "orbstack")
    monkeypatch.setenv("DOCKER_HOST", "unix:///Users/example/.docker/run/docker.sock")

    assert active_docker_context() == "default (DOCKER_HOST=unix:///Users/example/.docker/run/docker.sock)"


def test_validate_run_argv_rejects_single_token_with_spaces() -> None:
    with pytest.raises(typer.BadParameter) as exc_info:
        validate_run_argv(["node dist-server/foo.js"])

    message = str(exc_info.value)
    assert "--run node --run dist-server/foo.js" in message
    assert "node dist-server/foo.js" in message


def test_validate_run_argv_rejects_spaces_in_executable_with_extra_args() -> None:
    with pytest.raises(typer.BadParameter) as exc_info:
        validate_run_argv(["node dist-server/foo.js", "config.json"])

    message = str(exc_info.value)
    assert "--run node --run dist-server/foo.js --run config.json" in message
    assert "node dist-server/foo.js" in message


def test_validate_run_argv_allows_properly_split_argv() -> None:
    validate_run_argv(["node", "dist-server/foo.js"])


def test_validate_run_argv_allows_spaces_in_arguments() -> None:
    # Only the executable (argv[0]) must be a single token; arguments may contain spaces.
    validate_run_argv(["python", "-c", "print('a b')"])


def test_validate_run_argv_allows_single_token_without_spaces() -> None:
    validate_run_argv(["serve"])


def test_validate_run_argv_allows_none() -> None:
    validate_run_argv(None)


def test_observatory_web_url_strips_api_prefix_for_default_server() -> None:
    assert observatory_web_url("https://softmax.com/api", "/observatory/foo") == "https://softmax.com/observatory/foo"


def test_observatory_web_url_preserves_custom_api_host() -> None:
    assert (
        observatory_web_url("https://staging.softmax.com/api", "/observatory/foo")
        == "https://staging.softmax.com/observatory/foo"
    )
    assert (
        observatory_web_url("http://localhost:3000/api", "/observatory/foo") == "http://localhost:3000/observatory/foo"
    )


def test_observatory_web_url_strips_legacy_api_observatory_prefix() -> None:
    assert (
        observatory_web_url("https://staging.softmax.com/api/observatory", "/observatory/foo")
        == "https://staging.softmax.com/observatory/foo"
    )


def test_observatory_web_url_passes_through_absolute_urls() -> None:
    absolute = "https://api.example.com/v2/coworlds/proxy/client/global"
    assert observatory_web_url("https://softmax.com/api", absolute) == absolute
