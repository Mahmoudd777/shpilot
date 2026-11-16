import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import shpilot
from shpilot.cli import _guard, _output, builds
from shpilot.cli._context import BRANCH_ENV, PROJECT_ENV


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Run in an empty directory, with none of `shpilot`'s variables set and no git configuration of the user's."""
    monkeypatch.delenv(PROJECT_ENV, raising=False)
    monkeypatch.delenv(BRANCH_ENV, raising=False)
    monkeypatch.delenv("SHPILOT_DEBUG", raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    # A stray repository above `tmp_path` is not this test's checkout.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def guard_kept_apart(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the production guard off the user's desktop, terminal and `guard.json`, and let it through.

    The guard's own tests turn it back on with the `guarded` fixture.
    """
    monkeypatch.setattr(_guard, "config_path", lambda: tmp_path / "guard.json")
    monkeypatch.setattr(_guard, "_dialog", lambda *_, **__: None)
    monkeypatch.setattr(_guard, "_terminal", lambda *_, **__: None)
    _guard._write({"*"})  # noqa: SLF001


@pytest.fixture
def guarded(tmp_path: Path) -> None:
    """Turn the production guard back on: every project asks, and no one can be asked unless a test says so."""
    _guard._write(set())  # noqa: SLF001


@pytest.fixture(autouse=True)
def unreached(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., object]]:
    """Fail a test that reaches the library's client, login or logout, and return what stands for the client.

    A file's own stand-ins replace these.
    """
    reached: list[str] = []

    def refuse(name: str) -> Callable[..., object]:
        def refused(*_: object, **__: object) -> object:
            reached.append(name)
            msg = f"shpilot.{name} has no stand-in."

            raise AssertionError(msg)

        return refused

    refusals = {name: refuse(name) for name in ("Client", "login", "logout")}

    for name, refused in refusals.items():
        monkeypatch.setattr(shpilot, name, refused)

    yield refusals["Client"]
    # The command reports the error as its own, with an exit code a test may expect.
    assert reached == [], "A command reached the library with no stand-in."


@pytest.fixture(autouse=True)
def no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail a test that would start the user's browser. A file's own stand-in replaces it."""

    def refused(url: str) -> bool:
        msg = f"A browser was started for {url}."
        raise AssertionError(msg)

    monkeypatch.setattr(builds, "_browse", refused)


@pytest.fixture(autouse=True)
def read_only_clients(unreached: Callable[..., object]) -> Iterator[None]:
    """Fail a test whose command built a client that writes. Test files of the commands that may write replace it."""
    yield

    if shpilot.Client is unreached:
        return

    # `unreached` is asked for so that the test's stand-in is still in place here.
    modes: list[bool] | None = getattr(shpilot.Client, "modes", None)
    assert modes is not None, "The stand-in for `shpilot.Client` has to record each `read_only` in `modes`."
    assert all(modes), "A command built a client that is not read-only."


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make stdout a terminal that takes colour, for `shpilot` and for Rich."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    monkeypatch.setattr(_output, "_is_terminal", lambda: True)


def _git(*args: str) -> None:
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.com", *args], check=True)  # noqa: S603, S607


@pytest.fixture
def git() -> Callable[..., None]:
    """Run a git command in the current directory."""
    return _git


@pytest.fixture
def checkout() -> Callable[..., None]:
    """Make the current directory a repository on `branch`, with one commit and these remotes."""

    def checkout(branch: str = "feature-x", **remotes: str) -> None:
        _git("init", "--quiet", "--initial-branch", branch)
        _git("commit", "--quiet", "--allow-empty", "--message", "first")

        for name, url in remotes.items():
            _git("remote", "add", name, url)

    return checkout


# On native Windows shpilot does not hand over to `ssh` (it prints the command to run, exit 14), so the commands
# built on that handover, and the tests of POSIX file modes, are not run there. What Windows does instead is tested
# by the tests that name it.
_POSIX_ONLY_FILES = {"test_ssh.py", "test_backups_pull.py"}
_POSIX_ONLY_TESTS = {
    "test_the_file_is_private_whatever_the_umask",
    "test_writes_the_latest_backup_to_a_file_only_its_owner_reads",
    "test_a_directory_you_cannot_write_to_is_refused_before_any_change",
    "test_the_file_is_private_to_the_user",
    "test_login_writes_a_private_file_per_user_and_never_prints_the_session",
    "test_a_session_file_is_private_even_over_an_existing_one",
    "test_an_existing_out_directory_keeps_its_mode",
    "test_ssh_builds_a_client_that_writes_only_to_allow_the_address",
}
_POSIX_ONLY_PARAMS = {"backups pull", "ssh", "web-session login", "web-session logout"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if sys.platform != "win32":
        return
    skip = pytest.mark.skip(reason="POSIX only: native Windows prints the ssh command instead, and has no file modes.")
    for item in items:
        name = item.name.split("[", 1)[0]
        param = item.name[len(name) + 1 : -1] if "[" in item.name else ""
        windows_test = "windows" in name
        if (item.path.name in _POSIX_ONLY_FILES and not windows_test) or name in _POSIX_ONLY_TESTS or (
            name == "test_only_the_writers_build_a_client_that_writes" and param in _POSIX_ONLY_PARAMS
        ):
            item.add_marker(skip)
