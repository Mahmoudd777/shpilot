import json

import click
import pytest
from typer.testing import CliRunner

import shpilot
import shpilot.cli
from shpilot.cli import app as app_module
from shpilot.cli.app import app, main


runner = CliRunner()


def test_version_reports_the_cli_and_the_library():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"shpilot {shpilot.cli.__version__} (based on {shpilot.BASED_ON})"


def test_version_as_json_is_one_object():
    result = runner.invoke(app, ["--format", "json", "--version"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"shpilot": shpilot.cli.__version__, "based_on": shpilot.BASED_ON}


def test_no_arguments_shows_help():
    result = runner.invoke(app, [])

    # Unstyled first: where colour is forced, as it is on a CI runner, the help renderer styles the
    # dashes and the name of an option separately, so the raw output never contains the flag whole.
    output = click.unstyle(result.output)
    assert "Usage:" in output
    assert "--version" in output


def test_main_runs_the_application(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    monkeypatch.setattr(app_module, "app", lambda: calls.append("run"))
    main()

    assert calls == ["run"]
