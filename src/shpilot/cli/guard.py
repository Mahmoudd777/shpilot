"""`shpilot guard`: which projects' production changes run without asking."""

from typing import Annotated

import typer

from shpilot.cli import _guard
from shpilot.cli._errors import EXIT_GUARDED
from shpilot.cli._output import Output, strip_control


app = typer.Typer(
    name="guard",
    help="Show and change which projects' production changes run without asking.",
    no_args_is_help=True,
    epilog="Example: shpilot guard show",
)

ProjectArgument = Annotated[str, typer.Argument(help="The project's name, or * for every project.", show_default=False)]


@app.command(epilog="Example: shpilot guard show")
def show(ctx: typer.Context) -> None:
    """List the projects whose production changes run without asking. Every other project asks first."""
    output: Output = ctx.obj
    names = sorted(_guard.allowed())
    output.stream([{"allowed_without_asking": names, "file": str(_guard.config_path())}],
                  lambda found: ("Every project asks before a production change."
                                 if not found["allowed_without_asking"]
                                 else "Run without asking: " + ", ".join(found["allowed_without_asking"]))
                  + f"\n({found['file']})")


@app.command(epilog="Example: shpilot guard allow acme")
def allow(project: ProjectArgument) -> None:
    """Let production changes on PROJECT run without asking. A person has to say yes to this, on the desktop or the terminal."""
    if project in _guard.allowed() or "*" in _guard.allowed():
        typer.echo(strip_control(f"{project} already runs without asking."), err=True)
        return
    if not _guard.confirm_allow(project):
        typer.echo("Not changed: no one said yes, or no one could be asked.", err=True)
        raise typer.Exit(EXIT_GUARDED)
    names = _guard.allowed() | {project}
    _guard._write(names)  # noqa: SLF001
    typer.echo(strip_control(f"Production changes on {project} now run without asking."), err=True)


@app.command(epilog="Example: shpilot guard ask acme")
def ask(project: ProjectArgument) -> None:
    """Ask again before every production change on PROJECT. Needs no one's yes: it only makes the guard stricter."""
    changed = _guard.forget(project)
    typer.echo(strip_control(f"{project} asks before production changes." if changed else f"{project} already asks."), err=True)
