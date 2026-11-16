import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

import shpilot
from shpilot.cli import _guard
from shpilot.cli._errors import EXIT_GUARDED
from shpilot.cli.app import app


runner = CliRunner()
# The real ones, taken before the fixtures in conftest stand in for them.
REAL_CONFIG_PATH = _guard.config_path
REAL_TERMINAL = _guard._terminal  # noqa: SLF001


def branch(stage: shpilot.Stage) -> shpilot.Branch:
    return shpilot.Branch(id=1, name="main", stage=stage, stage_name=stage.value)


def answering(monkeypatch: pytest.MonkeyPatch, answer: str | None) -> list[str]:
    asked: list[str] = []

    def ask(text: str, project: str, **_: object) -> str | None:
        asked.append(text)
        return answer

    monkeypatch.setattr(_guard, "_ask", ask)
    return asked


@pytest.mark.usefixtures("guarded")
@pytest.mark.parametrize("stage", [shpilot.Stage.STAGING, shpilot.Stage.DEVELOPMENT])
def test_a_branch_outside_production_is_never_asked_about(monkeypatch: pytest.MonkeyPatch, stage: shpilot.Stage):
    asked = answering(monkeypatch, None)

    _guard.require("acme", "Rebuild.", branch=branch(stage))

    assert asked == []


@pytest.mark.usefixtures("guarded")
@pytest.mark.parametrize("stage", [shpilot.Stage.PRODUCTION, shpilot.Stage.UNKNOWN])
def test_production_and_an_unknown_stage_stop_when_no_one_can_be_asked(monkeypatch: pytest.MonkeyPatch, stage: shpilot.Stage, capsys):
    answering(monkeypatch, None)

    with pytest.raises(Exception) as stopped:
        _guard.require("acme", "Rebuild.", branch=branch(stage))

    assert getattr(stopped.value, "exit_code", None) == EXIT_GUARDED
    assert "your own terminal" in capsys.readouterr().err


@pytest.mark.usefixtures("guarded")
def test_a_project_wide_change_is_always_asked_about(monkeypatch: pytest.MonkeyPatch):
    asked = answering(monkeypatch, "once")

    _guard.require("acme", "Add jane as admin.")

    assert len(asked) == 1
    assert "the whole project acme" in asked[0]


@pytest.mark.usefixtures("guarded")
def test_no_is_exit_16_and_nothing_is_kept(monkeypatch: pytest.MonkeyPatch):
    answering(monkeypatch, "no")

    with pytest.raises(Exception) as stopped:
        _guard.require("acme", "Rebuild.", branch=branch(shpilot.Stage.PRODUCTION))

    assert getattr(stopped.value, "exit_code", None) == EXIT_GUARDED
    assert _guard.allowed() == set()


@pytest.mark.usefixtures("guarded")
def test_once_goes_ahead_without_keeping_anything(monkeypatch: pytest.MonkeyPatch):
    answering(monkeypatch, "once")

    _guard.require("acme", "Rebuild.", branch=branch(shpilot.Stage.PRODUCTION))

    assert _guard.allowed() == set()


@pytest.mark.usefixtures("guarded")
def test_always_is_kept_for_that_project_only(monkeypatch: pytest.MonkeyPatch):
    answering(monkeypatch, "always")
    _guard.require("acme", "Rebuild.", branch=branch(shpilot.Stage.PRODUCTION))
    asked = answering(monkeypatch, None)

    _guard.require("acme", "Rebuild again.", branch=branch(shpilot.Stage.PRODUCTION))
    with pytest.raises(Exception):
        _guard.require("other", "Rebuild.", branch=branch(shpilot.Stage.PRODUCTION))

    assert _guard.allowed() == {"acme"}
    assert len(asked) == 1


@pytest.mark.usefixtures("guarded")
def test_the_file_is_private_to_the_user(monkeypatch: pytest.MonkeyPatch):
    answering(monkeypatch, "always")

    _guard.require("acme", "Rebuild.", branch=branch(shpilot.Stage.PRODUCTION))

    assert oct(_guard.config_path().stat().st_mode & 0o777) == "0o600"
    assert json.loads(_guard.config_path().read_text()) == {"allow": ["acme"]}


def test_the_file_is_found_from_the_user_database_not_the_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    before = REAL_CONFIG_PATH()
    monkeypatch.setenv("HOME", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "elsewhere"))

    assert REAL_CONFIG_PATH() == before
    assert not str(before).startswith(str(tmp_path))


@pytest.mark.usefixtures("guarded")
def test_ask_needs_no_one_and_allow_needs_a_yes(monkeypatch: pytest.MonkeyPatch):
    answering(monkeypatch, None)

    refused = runner.invoke(app, ["guard", "allow", "acme"])
    _guard._write({"acme"})  # noqa: SLF001
    stricter = runner.invoke(app, ["guard", "ask", "acme"])

    assert refused.exit_code == EXIT_GUARDED
    assert stricter.exit_code == 0
    assert _guard.allowed() == set()


class FakeTerminal:
    def __init__(self, typed: str) -> None:
        self.typed, self.shown = typed, ""

    def __enter__(self):
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def write(self, text: str) -> None:
        self.shown += text

    def flush(self) -> None:
        pass

    def readline(self) -> str:
        return self.typed


@pytest.mark.parametrize(("typed", "answer"), [("a\n", "always"), ("o\n", "once"), ("\n", "no"), ("yes\n", "no")])
def test_a_terminal_answer_is_read_from_the_terminal_not_stdin(monkeypatch: pytest.MonkeyPatch, typed: str, answer: str):
    opened: list[str] = []
    terminal = FakeTerminal(typed)

    def fake_open(path, *_, **__):
        opened.append(path)
        return terminal

    monkeypatch.setattr("builtins.open", fake_open)
    monkeypatch.setattr("sys.stdin", None)

    assert REAL_TERMINAL("Rebuild.", "acme", always=True) == answer
    assert opened == ["/dev/tty"]
    assert "[N]o" in terminal.shown


def test_an_agents_shell_has_no_terminal_to_answer_from():
    # What an agent's shell looks like: no controlling terminal, so /dev/tty cannot be opened.
    if os.environ.get("CI") or not Path("/dev/tty").exists():
        pytest.skip("Needs a POSIX machine.")
    try:
        os.close(os.open("/dev/tty", os.O_RDWR))
    except OSError:
        assert REAL_TERMINAL("Rebuild.", "acme", always=True) is None
    else:
        pytest.skip("This run has a terminal.")


# What the second security review found, kept found.


@pytest.mark.usefixtures("guarded")
@pytest.mark.parametrize("project", ["*", "a*", "", "-x", "acme; rm"])
def test_a_wildcard_or_odd_project_name_is_refused_before_anyone_is_asked(monkeypatch: pytest.MonkeyPatch, project: str):
    asked = answering(monkeypatch, "always")

    with pytest.raises(Exception) as stopped:
        _guard.require(project, "Change the project's settings.")

    assert getattr(stopped.value, "exit_code", None) == EXIT_GUARDED
    assert asked == []
    assert _guard.allowed() == set()


REAL_DIALOG = _guard._dialog  # noqa: SLF001


def done(code: int, out: str = "", err: str = "") -> object:
    import subprocess

    return subprocess.CompletedProcess([], code, out, err)


@pytest.fixture
def desktop(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    ran: list[list[str]] = []
    monkeypatch.setattr(_guard, "_has_desktop", lambda: True)
    monkeypatch.setattr(_guard.sys, "platform", "linux")
    return ran


def only(monkeypatch: pytest.MonkeyPatch, program: str) -> None:
    monkeypatch.setattr(_guard.os, "access", lambda path, _mode: path == program)


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (done(0), "once"),
        (done(1, "Always for acme\n"), "always"),
        (done(1), "no"),
        (done(5), "no"),
        (done(1, "", "Gtk-WARNING: theme"), "no"),
        (done(1, "", "cannot open display: :0"), None),
        (done(255), None),
    ],
)
def test_zenity_answers_map_only_to_what_was_clicked(monkeypatch, desktop, answer, expected):
    only(monkeypatch, "/usr/bin/zenity")
    monkeypatch.setattr(_guard, "_run", lambda command: desktop.append(command) or answer)

    assert REAL_DIALOG("Rebuild.", "acme", always=True) == expected
    assert desktop[0][0] == "/usr/bin/zenity"


@pytest.mark.parametrize(("code", "expected"), [(0, "once"), (1, "no"), (2, None), (254, None)])
def test_kdialog_never_gives_always(monkeypatch, desktop, code, expected):
    only(monkeypatch, "/usr/bin/kdialog")
    monkeypatch.setattr(_guard, "_run", lambda command: desktop.append(command) or done(code))

    assert REAL_DIALOG("Rebuild.", "acme", always=True) == expected
    assert desktop[0][0] == "/usr/bin/kdialog"
    assert not any("Always" in part for part in desktop[0])


def test_a_dialog_program_on_path_is_never_used(monkeypatch, desktop, tmp_path: Path):
    fake = tmp_path / "zenity"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setattr(_guard.os, "access", lambda path, _mode: str(path) == str(fake))
    monkeypatch.setattr(_guard, "_run", lambda command: pytest.fail(f"ran {command}"))

    assert REAL_DIALOG("Rebuild.", "acme", always=True) is None




# Windows, simulated: its folders come from Windows, its dialog from Windows PowerShell at System32.


def test_on_windows_the_file_lives_in_the_folder_windows_reports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from shpilot import winpaths

    monkeypatch.setattr(_guard.sys, "platform", "win32")
    monkeypatch.setattr(winpaths, "roaming_app_data", lambda: tmp_path / "Roaming")
    monkeypatch.setenv("APPDATA", str(tmp_path / "planted"))

    assert REAL_CONFIG_PATH() == tmp_path / "Roaming" / "shpilot" / "guard.json"


def test_on_windows_with_no_folder_nothing_is_kept_and_always_is_not_offered(monkeypatch: pytest.MonkeyPatch):
    from shpilot import winpaths

    monkeypatch.setattr(_guard.sys, "platform", "win32")
    monkeypatch.setattr(winpaths, "roaming_app_data", lambda: None)
    monkeypatch.setattr(_guard, "config_path", REAL_CONFIG_PATH)
    offered: list[bool] = []
    monkeypatch.setattr(_guard, "_ask", lambda text, project, *, always=True: offered.append(always) or "once")

    _guard.require("acme", "Rebuild.", branch=branch(shpilot.Stage.PRODUCTION))

    assert _guard.allowed() == set()
    assert offered == [False]


@pytest.mark.parametrize(("printed", "code", "expected"), [
    ("always\r\n", 0, "always"), ("once\r\n", 0, "once"), ("no\r\n", 0, "no"), ("", 0, "no"), ("once", 1, None),
])
def test_the_windows_dialog_runs_system_powershell_and_maps_its_answer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, printed: str, code: int, expected: str | None
):
    import base64

    from shpilot import winpaths

    system = tmp_path / "System32"
    powershell = system / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    powershell.parent.mkdir(parents=True)
    powershell.write_text("")
    monkeypatch.setattr(_guard.sys, "platform", "win32")
    monkeypatch.setattr(winpaths, "system_directory", lambda: system)
    ran: list[list[str]] = []
    monkeypatch.setattr(_guard, "_run", lambda command: ran.append(command) or done(code, printed))

    answer = REAL_DIALOG("It's production.", "acme", always=True)

    assert answer == expected
    assert ran[0][0] == str(powershell)
    script = base64.b64decode(ran[0][ran[0].index("-EncodedCommand") + 1]).decode("utf-16-le")
    # The text is a PowerShell string literal, its quote doubled: it cannot end the string early.
    assert "'It''s production.'" in script
    assert "'Always for acme'" in script


def test_without_system_powershell_the_windows_dialog_is_not_shown(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from shpilot import winpaths

    monkeypatch.setattr(_guard.sys, "platform", "win32")
    monkeypatch.setattr(winpaths, "system_directory", lambda: tmp_path)
    monkeypatch.setattr(_guard, "_run", lambda command: pytest.fail(f"ran {command}"))

    assert REAL_DIALOG("Rebuild.", "acme", always=True) is None
