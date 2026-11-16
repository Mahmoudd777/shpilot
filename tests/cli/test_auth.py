import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Self

import click
import pytest
import typer
from typer.testing import CliRunner, Result

import shpilot
from shpilot.cli import _time, auth
from shpilot.cli.app import app


SENTINEL = "sentinel-session-value"
NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
STORED = shpilot.SessionInfo(shpilot.SessionSource.KEYRING, NOW - timedelta(days=3), NOW + timedelta(days=27))
GIVEN = shpilot.SessionInfo(shpilot.SessionSource.ENVIRONMENT, None, None)

runner = CliRunner()


class StubClient:
    """Stands in for `shpilot.Client`: holds a session and answers or raises."""

    info: shpilot.SessionInfo = STORED
    error: shpilot.OdoucheError | None = None
    modes: list[bool]
    """The `read_only` each client was built with."""
    rejected: shpilot.OdoucheError | None = None
    asked: int = 0

    def __init__(self, *, read_only: bool = False) -> None:
        self.modes.append(read_only)
        self._held = shpilot.Secret(SENTINEL)

        if self.error is not None:
            raise self.error

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    @property
    def session(self) -> shpilot.SessionInfo:
        return self.info

    def identity(self) -> shpilot.Identity:
        type(self).asked += 1

        if self.rejected is not None:
            raise self.rejected

        return shpilot.Identity(
            user_id=7, name="Ada Lovelace", username="ada", email="ada@example.com", session=self.info
        )


@pytest.fixture(autouse=True)
def client(monkeypatch: pytest.MonkeyPatch) -> type[StubClient]:
    class Client(StubClient):
        modes: list[bool] = []

    monkeypatch.delenv(shpilot.SESSION_ENV, raising=False)
    monkeypatch.setattr(shpilot, "Client", Client)
    monkeypatch.setattr(_time, "_now", lambda: NOW)

    return Client


def run(*args: str, stdin: str | None = None) -> Result:
    return runner.invoke(app, list(args), input=stdin)


def log_in(monkeypatch: pytest.MonkeyPatch, *steps: shpilot.LoginStep, error: shpilot.OdoucheError | None = None):
    """Replace `shpilot.login` with one that goes through `steps`, and return what it was asked for."""
    pasted: list[shpilot.Secret] = []

    def login(
        *,
        ask: Callable[[], shpilot.Secret] | None = None,
        notify: Callable[[shpilot.LoginStep], None],
        use: str | None = None,
        paste: bool = False,
    ) -> None:
        for step in steps:
            notify(step)

            if step is shpilot.LoginStep.PASTE:
                pasted.append(ask())

        if error is not None:
            raise error

    monkeypatch.setattr(shpilot, "login", login)

    return pasted


def log_out(monkeypatch: pytest.MonkeyPatch, result: shpilot.LogoutResult) -> None:
    monkeypatch.setattr(shpilot, "logout", lambda: result)


def test_login_names_the_user(monkeypatch: pytest.MonkeyPatch):
    log_in(monkeypatch, shpilot.LoginStep.KEYRING, shpilot.LoginStep.BROWSER)

    result = run("auth", "login", "--window")

    assert result.exit_code == 0
    assert result.stdout == "Logged in as ada.\n"
    assert "keyring" in result.stderr
    assert "browser" in result.stderr


def test_login_says_the_session_is_stored_before_asking_who_it_belongs_to(
    monkeypatch: pytest.MonkeyPatch, client: type[StubClient]
):
    log_in(monkeypatch)
    client.rejected = shpilot.UpstreamUnavailableError("Odoo.sh cannot be reached.")
    result = run("auth", "login", "--window")

    assert result.exit_code == 7
    assert "The session is stored in the keyring." in result.stderr


def test_login_as_json_is_the_identity(monkeypatch: pytest.MonkeyPatch):
    log_in(monkeypatch)

    result = run("--format", "json", "auth", "login", "--window")

    assert json.loads(result.stdout)["identity"]["username"] == "ada"


def test_login_asks_for_a_pasted_session_without_echo(monkeypatch: pytest.MonkeyPatch):
    pasted = log_in(monkeypatch, shpilot.LoginStep.PASTE)
    result = run("auth", "login", "--paste", stdin=f"{SENTINEL}\n")

    assert result.exit_code == 0
    assert [secret.expose_secret() for secret in pasted] == [SENTINEL]
    assert "session_id" in result.stderr
    assert SENTINEL not in result.output


def test_a_failed_login_is_its_exit_code(monkeypatch: pytest.MonkeyPatch, client: type[StubClient]):
    log_in(monkeypatch, error=shpilot.LoginError("No session captured."))

    result = run("auth", "login", "--window")

    assert result.exit_code == 12
    assert result.stdout == ""
    assert client.asked == 0


def test_login_does_not_name_the_user_of_the_environment_session(
    monkeypatch: pytest.MonkeyPatch, client: type[StubClient]
):
    log_in(monkeypatch)
    monkeypatch.setenv(shpilot.SESSION_ENV, SENTINEL)

    result = run("--format", "json", "auth", "login", "--window")

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"identity": None}
    assert shpilot.SESSION_ENV in result.stderr
    assert client.asked == 0


def test_status_shows_the_source_the_age_and_the_time_left(client: type[StubClient]):
    result = run("auth", "status")

    assert result.exit_code == 0
    assert result.stdout.splitlines() == ["Source   keyring", "Stored   3 days ago", "Expires  in 27 days"]
    assert client.asked == 0


def test_status_of_an_environment_session_has_no_age(client: type[StubClient]):
    client.info = GIVEN
    result = run("auth", "status")

    assert result.stdout.splitlines() == ["Source   environment", "Stored   unknown", "Expires  unknown"]


def test_status_as_json_is_the_session_info():
    result = run("--format", "json", "auth", "status")

    assert json.loads(result.stdout) == {
        "source": "keyring",
        "stored_at": "2026-10-01T12:00:00+00:00",
        "expires_at": "2026-10-31T12:00:00+00:00",
    }


@pytest.mark.parametrize("error", [shpilot.NoSessionError("Not logged in."), shpilot.SessionExpiredError("Too old.")])
def test_status_without_a_usable_session_exits_3(client: type[StubClient], error: shpilot.OdoucheError):
    client.error = error
    result = run("auth", "status")

    assert result.exit_code == 3
    assert result.stdout == ""


def test_status_check_asks_odoo_sh_who_the_session_belongs_to(client: type[StubClient]):
    result = run("auth", "status", "--check")

    assert result.exit_code == 0
    assert client.asked == 1
    assert result.stdout.splitlines()[:3] == ["User     ada", "Name     Ada Lovelace", "Email    ada@example.com"]
    assert "Source   keyring" in result.stdout


def test_status_check_as_json_is_the_identity():
    result = run("--format", "json", "auth", "status", "--check")
    found = json.loads(result.stdout)
    assert found["username"] == "ada"
    assert found["session"]["source"] == "keyring"


def test_status_check_of_a_rejected_session_exits_3(client: type[StubClient]):
    client.rejected = shpilot.SessionExpiredError("Odoo.sh no longer accepts the session.")
    result = run("auth", "status", "--check")

    assert result.exit_code == 3
    assert result.stdout == ""


LOGOUTS: list[tuple[shpilot.LogoutResult, list[str]]] = [
    (shpilot.LogoutResult(None, deleted=False, invalidated=False, failure=None), ["Not logged in."]),
    (
        shpilot.LogoutResult(shpilot.SessionSource.KEYRING, deleted=True, invalidated=True, failure=None),
        ["removed from the keyring", "and ended on Odoo.sh"],
    ),
    (
        shpilot.LogoutResult(shpilot.SessionSource.KEYRING, deleted=True, invalidated=False, failure=None),
        ["removed from the keyring", "was not ended on Odoo.sh"],
    ),
    (
        shpilot.LogoutResult(
            shpilot.SessionSource.KEYRING,
            deleted=True,
            invalidated=False,
            failure=shpilot.UpstreamUnavailableError("Odoo.sh cannot be reached."),
        ),
        ["removed from the keyring", "could not be asked", "Odoo.sh cannot be reached."],
    ),
    (
        shpilot.LogoutResult(shpilot.SessionSource.ENVIRONMENT, deleted=False, invalidated=False, failure=None),
        [shpilot.SESSION_ENV, "cannot unset"],
    ),
]
LOGOUT_IDS = ["none", "ended", "not-ended", "unreachable", "environment"]


@pytest.mark.parametrize(("outcome", "said"), LOGOUTS, ids=LOGOUT_IDS)
def test_logout_says_what_it_did(monkeypatch: pytest.MonkeyPatch, outcome: shpilot.LogoutResult, said: list[str]):
    log_out(monkeypatch, outcome)

    result = run("auth", "logout")

    assert result.exit_code == 0

    for text in said:
        assert text in result.stdout


def test_logout_as_json_has_the_failure_as_its_message(monkeypatch: pytest.MonkeyPatch):
    log_out(monkeypatch, LOGOUTS[3][0])

    result = run("--format", "json", "auth", "logout")

    assert json.loads(result.stdout) == {
        "source": "keyring",
        "deleted": True,
        "invalidated": False,
        "failure": "Odoo.sh cannot be reached.",
    }


@pytest.mark.parametrize("output_format", ["table", "json"])
@pytest.mark.parametrize("command", [("login", "--paste"), ("status",), ("status", "--check"), ("logout",)])
@pytest.mark.parametrize("source", [shpilot.SessionSource.KEYRING, shpilot.SessionSource.ENVIRONMENT])
def test_the_session_is_in_neither_stream(
    monkeypatch: pytest.MonkeyPatch, output_format: str, command: tuple[str, ...], source: shpilot.SessionSource
):
    log_in(monkeypatch, shpilot.LoginStep.PASTE)
    given = source is shpilot.SessionSource.ENVIRONMENT
    log_out(monkeypatch, LOGOUTS[4][0] if given else LOGOUTS[1][0])

    if given:
        monkeypatch.setenv(shpilot.SESSION_ENV, SENTINEL)

    result = run("--format", output_format, "--debug", "auth", *command, stdin=f"{SENTINEL}\n")

    assert result.exit_code == 0
    assert SENTINEL not in result.stdout
    assert SENTINEL not in result.stderr


def test_no_option_takes_a_session():
    group: Any = typer.main.get_command(auth.app)
    names = [name for command in group.commands.values() for param in command.params for name in param.opts]

    assert set(group.commands) == {"login", "status", "logout", "browsers"}
    assert "--check" in names
    assert not [name for name in names if "session" in name or "cookie" in name]


def test_help_opens_neither_the_keyring_nor_the_network(client: type[StubClient]):
    client.error = shpilot.KeyringUnavailableError()
    result = run("auth", "--help")

    assert result.exit_code == 0
    assert "login" in click.unstyle(result.output)


def test_login_without_a_way_and_without_a_terminal_lists_the_choices(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(shpilot, "browsers", lambda: [shpilot.BrowserLogin("firefox", "Firefox", signed_in=True)])
    asked = log_in(monkeypatch)

    result = run("auth", "login")
    # Styled where colour is forced (CI), and wrapped in a box: compare the words only.
    words = " ".join(click.unstyle(result.output).replace("│", " ").split())

    assert result.exit_code == 2
    assert "--from firefox" in words
    assert "--window" in words
    assert asked == []


def test_login_from_a_browser_reads_that_browser_only(monkeypatch: pytest.MonkeyPatch, client: type[StubClient]):
    used: list[str | None] = []

    def login(*, notify: Callable[[shpilot.LoginStep], None], use: str | None = None, **_: object) -> None:
        used.append(use)
        notify(shpilot.LoginStep.REUSE)

    monkeypatch.setattr(shpilot, "login", login)

    result = run("auth", "login", "--from", "brave")

    assert result.exit_code == 0, result.output
    assert used == ["brave"]
    assert "browser you picked" in result.stderr


def test_login_takes_one_way_only():
    assert run("auth", "login", "--window", "--paste").exit_code == 2


def test_browsers_lists_the_ways_without_reading_a_cookie(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(shpilot, "browsers", lambda: [shpilot.BrowserLogin("brave", "Brave", signed_in=False)])

    result = run("--format", "json", "auth", "browsers")

    assert [json.loads(line)["id"] for line in result.stdout.splitlines()] == ["brave", "window", "paste"]
