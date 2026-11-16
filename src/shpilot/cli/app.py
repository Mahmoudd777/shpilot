"""The `shpilot` command: the root application and its entry point."""

from dataclasses import dataclass
from typing import Annotated

import typer

import shpilot
from shpilot.cli import __version__, auth, backups, branches, builds, guard, logs, projects, ssh, web_session
from shpilot.cli._errors import DebugOption, OshGroup
from shpilot.cli._output import Format, FormatOption, Output


app = typer.Typer(
    name="shpilot",
    help="Work with Odoo.sh projects from the command line (unofficial).",
    no_args_is_help=True,
    cls=OshGroup,
    # A locals dump is where a session would surface.
    pretty_exceptions_show_locals=False,
)
app.add_typer(auth.app)
app.add_typer(backups.app)
app.add_typer(branches.app)
app.add_typer(builds.app)
app.add_typer(guard.app)
app.command(epilog=logs.EPILOG)(logs.logs)
app.add_typer(projects.app)
app.add_typer(web_session.app)
# The options of `shpilot ssh` come first: what follows its first argument is `ssh`'s.
app.command(epilog=ssh.EPILOG, context_settings={"allow_interspersed_args": False})(ssh.ssh)


@dataclass(frozen=True, slots=True)
class Versions:
    """The versions `--version` reports."""

    shpilot: str
    based_on: str


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    *,
    version: Annotated[
        bool,
        typer.Option("--version", help="Show the version and exit.", is_eager=True),
    ] = False,
    debug: DebugOption = False,
    output_format: FormatOption = Format.TABLE,
) -> None:
    """Work with Odoo.sh projects from the command line (unofficial)."""
    output = ctx.obj = Output(output_format)

    if version:
        versions = Versions(shpilot=__version__, based_on=shpilot.BASED_ON)
        output.stream([versions], lambda found: f"shpilot {found.shpilot} (based on {found.based_on})")

        raise typer.Exit


def main() -> None:
    """Run the `shpilot` command."""
    app()
