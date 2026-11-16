"""Library errors as exit codes and messages, handled once at the root of `shpilot`.

Scripts branch on the codes, so changing one is a breaking change. `docs/cli.md` has the table.
"""

import os
import sys
import traceback
from contextlib import suppress
from typing import Annotated, Any, override

import typer
from typer.core import TyperGroup

import shpilot
from shpilot.cli._output import strip_control


ISSUES_URL = "https://github.com/Mahmoudd777/shpilot/issues"
EXIT_UNEXPECTED = 1
# What click exits with when a prompt is aborted.
EXIT_DECLINED = 1
_LOGIN = "Run `shpilot auth login`."
_LOGIN_AGAIN = "Run `shpilot auth login` again."

# What `shpilot builds watch` exits with, in the 20 to 29 kept for the result of a build.
EXIT_BUILD_FAILED = 20
EXIT_BUILD_WARNING = 21
EXIT_BUILD_NO_RESULT = 22
EXIT_BUILD_TIMEOUT = 23

# What `shpilot projects check` exits with, in the 30 to 39 kept for the result of a check.
EXIT_CHECK_FAILED = 30
EXIT_CHECK_WARNED = 31

# What `shpilot ssh` exits with when there is no `ssh` to become.
EXIT_NO_SSH = 14
# What `shpilot builds open --open` exits with when no browser opens: as with `shpilot ssh`, what to use
# by hand is shown.
EXIT_NO_BROWSER = 14

# What a command exits with when a change it sent was not confirmed.
EXIT_OUTCOME_UNKNOWN = 10

# What a command exits with when what it waited for did not come in time.
EXIT_TIMEOUT = 8

# What `shpilot backups download` exits with when the disk refuses the file.
EXIT_NOT_WRITTEN = 15

# What a command exits with when the production guard stops it: no one allowed it, or no one could be asked.
EXIT_GUARDED = 16

# What a shell reports for a command that SIGPIPE ended.
EXIT_CLOSED_PIPE = 141

# The first row an error is an instance of wins, so the base class comes last. 1 and 2 are the
# unexpected error and click's usage error.
EXIT_CODES: tuple[tuple[type[shpilot.OdoucheError], int, str | None], ...] = (
    (shpilot.NoSessionError, 3, _LOGIN),
    (shpilot.SessionExpiredError, 3, _LOGIN),
    (shpilot.NotFoundError, 4, None),
    (shpilot.PermissionDeniedError, 5, None),
    (shpilot.UpstreamChangedError, 6, None),
    (shpilot.UpstreamUnavailableError, 7, "Try again later."),
    (shpilot.StreamTimeoutError, EXIT_TIMEOUT, None),
    (shpilot.LoginTimeoutError, EXIT_TIMEOUT, _LOGIN_AGAIN),
    (shpilot.ReadOnlyError, 9, None),
    (shpilot.StageRefusedError, 9, None),
    (shpilot.MemberRefusedError, 9, None),
    (shpilot.OutcomeUnknownError, EXIT_OUTCOME_UNKNOWN, "`shpilot builds list` shows whether the build was started."),
    (shpilot.KeyringUnavailableError, 11, None),
    (shpilot.LoginError, 12, _LOGIN_AGAIN),
    (shpilot.OdoucheError, 13, None),
)

# Where to look after an unconfirmed change, by the operation the library names, when it is not a build.
_OUTCOME_HINTS = {
    "backup": "`shpilot backups list` shows whether the backup was taken.",
    "branch settings change": "`shpilot branches settings show` shows whether the settings were changed. Sending the "
    "same change again does no harm.",
    "project settings change": "`shpilot projects settings show` shows whether the settings were changed. Sending the "
    "same change again does no harm.",
    "branch stage move": "`shpilot branches list` shows the branch's stage. Running the move again is refused once the "
    "branch is there.",
    "member addition": "`shpilot projects members list` shows whether they were added. Adding them again is refused "
    "once they are a member.",
    "member role change": "`shpilot projects members list` shows their role. Setting the same role again sends nothing.",
    "download preparation": "Preparing the file again does no harm: run the command again, naming the backup rather "
    "than giving --new.",
}

DebugOption = Annotated[
    bool,
    typer.Option("--debug", envvar="SHPILOT_DEBUG", help="Show the traceback when a command fails."),
]


class OshGroup(TyperGroup):
    """The root group: a failed command ends with a message on stderr and an exit code."""

    @override
    def list_commands(self, ctx: typer.Context) -> list[str]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """List the commands by name: typer lists a command before every group."""
        return sorted(super().list_commands(ctx))

    # The base names typer's vendored click context, which is not public. Typer passes its own.
    @override
    def invoke(self, ctx: typer.Context) -> Any:  # pyright: ignore[reportIncompatibleMethodOverride]
        try:
            return super().invoke(ctx)
        except (typer.Exit, typer.Abort, typer.TyperException):
            raise
        # A pipe closed under a command's output, as by `| head`, ends the command quietly.
        except BrokenPipeError:
            _discard_stdout()
            ctx.exit(EXIT_CLOSED_PIPE)
        except Exception as error:  # noqa: BLE001 - the root reports every failure
            debug = bool(ctx.params.get("debug"))

            if debug:
                _print_traceback(error)

            ctx.exit(_report(error, debug=debug))


def _discard_stdout() -> None:
    """Point stdout at the null device, so that the flush at exit does not fail on the closed pipe."""
    # A stdout that is not a file has nothing to flush there.
    with suppress(OSError, ValueError):
        descriptor = sys.stdout.fileno()
        null = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null, descriptor)
        os.close(null)


def _print_traceback(error: Exception) -> None:
    """Print the standard traceback, which has no locals, with the environment's session masked.

    Each line loses its control characters first, so that one inside the session cannot hide it.
    """
    text = "".join(traceback.format_exception(error))
    text = "\n".join(strip_control(line) for line in text.split("\n"))

    if session := os.environ.get(shpilot.SESSION_ENV):
        text = text.replace(session, str(shpilot.Secret(session)))

    typer.echo(text, err=True, nl=False)


def _report(error: Exception, *, debug: bool) -> int:
    """Print what happened and what to do on stderr, and return the exit code."""
    if not isinstance(error, shpilot.OdoucheError):
        typer.echo(f"Unexpected error ({type(error).__name__}). Please report it at {ISSUES_URL}", err=True)

        if not debug:
            typer.echo("Run again with --debug for the traceback.", err=True)

        return EXIT_UNEXPECTED

    code, hint = next((code, hint) for kind, code, hint in EXIT_CODES if isinstance(error, kind))

    if isinstance(error, shpilot.OutcomeUnknownError):
        hint = _OUTCOME_HINTS.get(error.operation or "", hint)

    typer.echo(strip_control(str(error)), err=True)

    if hint:
        typer.echo(hint, err=True)

    return code
