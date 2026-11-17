"""`shpilot auth`: log in, log out, and say what session is in use."""

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

import typer

import shpilot
from shpilot.cli import _terminal
from shpilot.cli._client import open_client
from shpilot.cli._context import ContextError
from shpilot.cli._output import Column, Output
from shpilot.cli._time import ago, left


app = typer.Typer(
    name="auth",
    help="Log in to Odoo.sh, log out, and show the session in use.",
    epilog="Example: shpilot auth login",
    no_args_is_help=True,
)

_STEPS = {
    shpilot.LoginStep.KEYRING: "Checking the keyring. Unlock it if it asks.",
    shpilot.LoginStep.BROWSER: "A browser window is open: sign in to Odoo.sh with GitHub there.",
    shpilot.LoginStep.PASTE: (
        "Sign in to Odoo.sh in your own browser, then paste the session_id cookie of www.odoo.sh "
        "(developer tools, Storage or Application, Cookies)."
    ),
    shpilot.LoginStep.REUSE: "Reading the Odoo.sh login of the browser you picked. Unlock the keyring if it asks.",
}

_WINDOW = "window"
_PASTE = "paste"

_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Login:
    """What `shpilot auth login` did."""

    identity: shpilot.Identity | None
    """Who the stored session belongs to, or `None` when the environment's is the one in use."""


@dataclass(frozen=True, slots=True)
class Logout:
    """What `shpilot auth logout` did: the library's result, with the failure as its message."""

    source: shpilot.SessionSource | None
    deleted: bool
    invalidated: bool
    failure: str | None


@dataclass(frozen=True, slots=True)
class Way:
    """One way to log in on this machine, as `shpilot auth browsers` lists them."""

    id: str
    """What to give `shpilot auth login --from`, or `window` or `paste`."""

    label: str
    signed_in: bool
    """For a browser: whether it holds an Odoo.sh login. Whether Odoo.sh still accepts it is known only when used."""

    opens_window: bool = False
    """For a browser on Windows other than Firefox: picking it opens a sign-in window in it, with a fresh profile
    deleted after, since Windows locks the logins Chromium-family browsers hold to the browser itself."""


def _ways() -> list[Way]:
    ways = [Way(found.id, found.label, found.signed_in) for found in shpilot.browsers()]
    if sys.platform == "win32":
        listed = {way.id for way in ways}
        ways += [
            Way(browser_id, label, signed_in=False, opens_window=True)
            for browser_id, label, _ in shpilot.window_browsers()
            if browser_id not in listed
        ]
    else:
        ways.append(Way(_WINDOW, "A sign-in window (a fresh profile, deleted after; sign in to GitHub there)", False))
    ways.append(Way(_PASTE, "Paste the session_id cookie from your browser's developer tools", False))
    return ways


def _way_line(way: Way) -> str:
    if way.id in (_WINDOW, _PASTE):
        return f"{way.id:<9} {way.label}"
    if way.opens_window:
        return f"{way.id:<9} {way.label}, opens a sign-in window in it (a fresh profile, deleted after)"
    state = "holds an Odoo.sh login: reuse it, no sign-in" if way.signed_in else "holds no Odoo.sh login"
    return f"{way.id:<9} {way.label}, {state}"


def _opens_window(ctx: typer.Context, browser_id: str) -> bool:
    """Whether `--from <browser_id>` opens a sign-in window in that browser: on Windows, for all but Firefox, whose
    login is reused there as everywhere."""
    if sys.platform != "win32" or browser_id == "firefox":
        return False
    if not any(found == browser_id for found, _, _ in shpilot.window_browsers()):
        ways = ", ".join(way.id for way in _ways() if way.id not in (_WINDOW, _PASTE)) or "none"
        msg = f"{browser_id} is not installed here. Browsers here: {ways}. Or use --paste."
        raise ContextError(msg, ctx=ctx)
    return True


@app.command(epilog="Example: shpilot auth browsers --format json")
def browsers(ctx: typer.Context) -> None:
    """List the ways to log in here: the browsers on this machine and whether each holds an Odoo.sh login.

    Nothing is decrypted to list them. Give one to `shpilot auth login --from`.
    """
    output: Output = ctx.obj
    output.stream(_ways(), _way_line)


def _picked(ctx: typer.Context) -> str:
    """Ask the person at the terminal how to log in, or say how to choose when no one can be asked."""
    ways = _ways()
    if not (_terminal.stdin_is_terminal() and _terminal.stderr_is_terminal()):
        listed = "; ".join(f"--from {way.id}" if way.id not in (_WINDOW, _PASTE) else f"--{way.id}" for way in ways)
        msg = (
            "Say how to log in, as the user chooses: "
            f"{listed}. `shpilot auth browsers` says which browsers hold an Odoo.sh login."
        )
        raise ContextError(msg, ctx=ctx)
    typer.echo("How do you want to log in to Odoo.sh?", err=True)
    for number, way in enumerate(ways, 1):
        typer.echo(f"  {number}. {_way_line(way)}", err=True)
    answer = typer.prompt("Number", default="1", err=True)
    if not answer.isdigit() or not 1 <= int(answer) <= len(ways):
        msg = f"{answer!r} is not one of the numbers shown."
        raise ContextError(msg, ctx=ctx)
    return ways[int(answer) - 1].id


@app.command(epilog="Example: shpilot auth login --from firefox")
def login(
    ctx: typer.Context,
    *,
    from_browser: Annotated[
        str | None,
        typer.Option(
            "--from",
            help="Reuse the Odoo.sh login this browser already holds: firefox, chrome, chromium, brave, edge, "
            "vivaldi or opera. Only its www.odoo.sh session_id cookie is read. On Windows, every one but firefox "
            "opens a sign-in window in that browser instead, with a fresh profile deleted after.",
            show_default=False,
        ),
    ] = None,
    window: Annotated[bool, typer.Option("--window", help="Sign in with GitHub in a fresh browser window.")] = False,
    paste: Annotated[bool, typer.Option("--paste", help="Paste the session_id cookie in a prompt that does not echo it.")] = False,
) -> None:
    """Log in to Odoo.sh and store the session in the keyring.

    Three ways: reuse the login one of your browsers already holds (`--from`), sign in with GitHub in a fresh window
    whose profile is deleted afterwards (`--window`), or paste the session_id cookie (`--paste`). With none of them,
    it asks which, at a terminal; elsewhere, such as in an agent's shell, it exits 2 with the choices.
    """
    output: Output = ctx.obj
    if sum((from_browser is not None, window, paste)) > 1:
        msg = "Give one of --from, --window and --paste."
        raise ContextError(msg, ctx=ctx)
    chosen = from_browser or (_WINDOW if window else _PASTE if paste else _picked(ctx))
    notify = lambda step: typer.echo(_STEPS[step], err=True)  # noqa: E731
    if chosen == _WINDOW:
        shpilot.login(ask=_ask, notify=notify)
    elif chosen == _PASTE:
        shpilot.login(ask=_ask, notify=notify, paste=True)
    elif _opens_window(ctx, chosen):
        shpilot.login(ask=_ask, notify=notify, window=chosen)
    else:
        shpilot.login(notify=notify, use=chosen)
    typer.echo("The session is stored in the keyring.", err=True)

    if os.environ.get(shpilot.SESSION_ENV):
        typer.echo(f"{shpilot.SESSION_ENV} is set and is used instead of it until it is unset.", err=True)
        identity = None
    else:
        with open_client() as client:
            identity = client.identity()

    output.stream([Login(identity)], _login_line)


@app.command(epilog="Example: shpilot auth status --check")
def status(
    ctx: typer.Context,
    *,
    check: Annotated[
        bool,
        typer.Option("--check", help="Ask Odoo.sh whether it still accepts the session, and who it belongs to."),
    ] = False,
) -> None:
    """Show where the session comes from and how long it lasts, without asking Odoo.sh. Exits 3 when there is none."""
    output: Output = ctx.obj

    with open_client() as client:
        if not check:
            output.one(client.session, _session_columns(_itself))
            return

        identity = client.identity()

    output.one(
        identity,
        [
            Column[shpilot.Identity]("User", lambda found: found.username),
            Column[shpilot.Identity]("Name", lambda found: found.name),
            Column[shpilot.Identity]("Email", lambda found: found.email),
            *_session_columns(_session_of),
        ],
    )


@app.command(epilog="Example: shpilot auth logout")
def logout(ctx: typer.Context) -> None:
    """End the stored session on Odoo.sh and remove it from the keyring. Exits 0 when there is none."""
    output: Output = ctx.obj
    result = shpilot.logout()
    failure = None if result.failure is None else str(result.failure)
    output.stream([Logout(result.source, result.deleted, result.invalidated, failure)], _logout_line)


def _ask() -> shpilot.Secret:
    return shpilot.Secret(typer.prompt("session_id", hide_input=True, err=True))


def _itself(info: shpilot.SessionInfo) -> shpilot.SessionInfo:
    return info


def _session_of(identity: shpilot.Identity) -> shpilot.SessionInfo:
    return identity.session


def _session_columns[T](session: Callable[[T], shpilot.SessionInfo]) -> list[Column[T]]:
    return [
        Column[T]("Source", lambda item: session(item).source),
        Column[T]("Stored", lambda item: _ago(session(item).stored_at)),
        Column[T]("Expires", lambda item: _left(session(item).expires_at)),
    ]


def _ago(moment: datetime | None) -> str:
    return _UNKNOWN if moment is None else ago(moment)


def _left(moment: datetime | None) -> str:
    return _UNKNOWN if moment is None else left(moment)


def _login_line(result: Login) -> str:
    return "Logged in." if result.identity is None else f"Logged in as {result.identity.username}."


def _logout_line(result: Logout) -> str:
    if result.source is None:
        return "Not logged in."

    if not result.deleted:
        return (
            f"The session comes from {shpilot.SESSION_ENV}, which shpilot cannot unset. "
            "Nothing was changed: unset it yourself."
        )

    removed = "The stored session was removed from the keyring"

    if result.invalidated:
        return f"{removed} and ended on Odoo.sh."

    if result.failure is None:
        return f"{removed}. It was not ended on Odoo.sh."

    return f"{removed}. Odoo.sh could not be asked to end it, so a copy of it works until it expires: {result.failure}"
