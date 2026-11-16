import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

import shpilot
from shpilot.cli import web_session
from shpilot.cli.app import app


runner = CliRunner()
SID = "a" * 40
TARGET = shpilot.SshTarget(user="4242", host="acme-staging-4242.dev.odoo.com")
RUN = "0123456789abcdef01234567"


@pytest.fixture
def build(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stand in for the build: no client, no ssh. Returns the scripts it was sent."""
    sent: list[str] = []
    monkeypatch.setattr(web_session, "_target", lambda ctx, project, branch, yes: ("https://" + TARGET.host, TARGET))
    monkeypatch.setattr(web_session, "_answers", [], raising=False)

    def run(command, *, input, **_):  # noqa: A002
        sent.append(input)
        mark = input.split("= '", 1)[1].split("'", 1)[0]
        lines = [f"{mark} {json.dumps(answer)}" for answer in web_session._answers]
        lines += ["OUT not-ours", f"{'f' * 24} {json.dumps({'uid': 9, 'sid': SID})}"]
        return subprocess.CompletedProcess(command, 0, "\n".join(lines) + "\n", "")

    monkeypatch.setattr(subprocess, "run", run)
    return sent


def answer(*items: dict[str, object]) -> None:
    web_session._answers[:] = list(items)


def test_production_and_unknown_stages_are_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    class Client:
        def __init__(self, **_: object) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_: object) -> None:
            pass

    for stage in (shpilot.Stage.PRODUCTION, shpilot.Stage.UNKNOWN):
        branch = shpilot.Branch(id=1, name="main", stage=stage, stage_name=stage.value)
        monkeypatch.setattr(web_session, "open_client", lambda **_: Client())
        monkeypatch.setattr(web_session, "project_branch", lambda *_, b=branch: ("acme", b))

        out = tmp_path / "out"
        result = runner.invoke(app, ["web-session", "login", "--branch", "main", "--out", str(out), "admin"])

        assert result.exit_code == 9
        assert not out.exists()


def test_login_writes_a_private_file_per_user_and_never_prints_the_session(build: list[str], tmp_path: Path):
    out = tmp_path / "sessions"
    answer({"uid": 2, "login": "admin", "db": "acme-staging", "sid": SID})

    result = runner.invoke(app, ["web-session", "login", "--out", str(out), "admin"])

    assert result.exit_code == 0, result.output
    path = out / "2.session"
    written = json.loads(path.read_text())
    run = written.pop("run")
    assert written == {"url": f"https://{TARGET.host}", "db": "acme-staging", "uid": 2, "login": "admin", "sid": SID}
    # Every session of the run carries the run's tag on the build: a logout finds them by it, renamed or not.
    assert f"MARK, TAG, RUN = " in build[0] and repr(run) in build[0]
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(out.stat().st_mode & 0o777) == "0o700"
    assert SID not in result.output
    # The user keys reach the build inside its script, on stdin, as data.
    assert '["admin"]' in build[0]


def test_only_lines_with_this_runs_marker_are_believed(build: list[str], tmp_path: Path):
    answer()

    result = runner.invoke(app, ["web-session", "login", "--out", str(tmp_path), "admin"])

    # The build printed "OUT ..." and a line with another marker: neither wrote a file.
    assert result.exit_code == 1
    assert list(tmp_path.glob("*.session")) == []


@pytest.mark.parametrize(
    "item",
    [
        {"uid": "../escaped", "login": "x", "db": "d", "sid": SID},
        {"uid": 3, "login": "x", "db": "d", "sid": "short"},
        {"uid": 3, "login": "x", "db": "d", "sid": "has space " + SID},
    ],
)
def test_an_answer_that_is_not_a_session_is_ignored(build: list[str], tmp_path: Path, item: dict[str, object]):
    answer(item)

    result = runner.invoke(app, ["web-session", "login", "--out", str(tmp_path / "out"), "x"])

    assert result.exit_code == 1
    assert list((tmp_path / "out").glob("*")) == []
    assert not (tmp_path / "escaped.session").exists()


def test_a_key_with_quotes_stays_data(build: list[str], tmp_path: Path):
    answer()
    key = "x'); import os; os.system('id') #"

    runner.invoke(app, ["web-session", "login", "--out", str(tmp_path), key])

    script = build[0]
    compile(script, "<script>", "exec")
    assert "os.system('id')" not in script.replace(json.dumps([key]), "")


def test_logout_deletes_the_files_once_the_build_confirms(build: list[str], tmp_path: Path):
    (tmp_path / "2.session").write_text(json.dumps({"sid": SID, "run": RUN}))
    answer({"deleted": 1, "left": 0})

    result = runner.invoke(app, ["web-session", "logout", "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert list(tmp_path.glob("*.session")) == []
    # It deletes by the run's tag, and only tagged sessions: never one by its id alone.
    assert RUN in build[0]
    assert SID not in build[0]


@pytest.mark.parametrize("reply", [{"deleted": 0, "left": 1}, {"deleted": "x", "left": 0}])
def test_logout_keeps_the_files_when_the_build_does_not_confirm(build: list[str], tmp_path: Path, reply):
    (tmp_path / "2.session").write_text(json.dumps({"sid": SID, "run": RUN}))
    answer(reply)

    result = runner.invoke(app, ["web-session", "logout", "--out", str(tmp_path)])

    assert result.exit_code == 1
    assert (tmp_path / "2.session").exists()


def test_logout_all_asks_the_build_for_every_tagged_session(build: list[str], tmp_path: Path):
    answer({"deleted": 3, "left": 0})

    result = runner.invoke(app, ["web-session", "logout", "--all", "--out", str(tmp_path)])

    assert result.exit_code == 0, result.output
    # Odoo keeps sessions in sub-folders: the cleanup walks them, and keeps the ids it was given.
    assert "os.walk(store.path)" in build[0]
    assert "True or tag in runs" in build[0]
    assert web_session.TAG in build[0]


def test_a_session_file_is_private_even_over_an_existing_one(build: list[str], tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "2.session").write_text("{}")
    (out / "2.session").chmod(0o644)
    answer({"uid": 2, "login": "admin", "db": "d", "sid": SID})

    runner.invoke(app, ["web-session", "login", "--out", str(out), "admin"])

    assert oct((out / "2.session").stat().st_mode & 0o777) == "0o600"


def test_a_session_file_is_never_written_through_a_link(build: list[str], tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    target = tmp_path / "elsewhere"
    target.write_text("keep")
    (out / "2.session").symlink_to(target)
    answer({"uid": 2, "login": "admin", "db": "d", "sid": SID})

    result = runner.invoke(app, ["web-session", "login", "--out", str(out), "admin"])

    assert result.exit_code != 0
    assert target.read_text() == "keep"


def test_an_existing_out_directory_keeps_its_mode(build: list[str], tmp_path: Path):
    tmp_path.chmod(0o755)
    answer({"uid": 2, "login": "admin", "db": "d", "sid": SID})

    runner.invoke(app, ["web-session", "login", "--out", str(tmp_path), "admin"])

    assert oct(tmp_path.stat().st_mode & 0o777) == "0o755"


def test_ssh_forwards_nothing_to_the_build():
    assert "ForwardAgent=no" in web_session._SSH  # noqa: SLF001
    assert "ClearAllForwardings=yes" in web_session._SSH  # noqa: SLF001


def test_the_same_user_twice_is_one_session(build: list[str], tmp_path: Path):
    answer({"uid": 2, "login": "admin", "db": "d", "sid": SID})

    result = runner.invoke(app, ["web-session", "login", "--out", str(tmp_path), "admin", "admin"])

    assert result.exit_code == 0, result.output
    assert '["admin"]' in build[0]
