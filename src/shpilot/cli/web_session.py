"""`shpilot web-session`: a browser session on a staging or development build, as any of its users, with no password.

The session is made on the build itself, over `ssh`, by `odoo-bin shell`: the same record a login makes, written to
the build's session store. Nothing goes through the login page, so no password and no second factor is needed, and
the user's own sessions are untouched. Production is refused, always, whatever the guard allows.

A staging build holds a copy of production's data: the people, the invoices, the mail. Whatever a test reads there,
screenshots included, is customer data.

What is kept apart:

- The session id goes to the build on `ssh`'s stdin and comes back on its stdout, never on a command line. It is
  written to a file only the user can read, and never printed.
- Lines from the build are read only when they carry this run's random marker and parse as JSON: a module on the
  branch that prints its own lines cannot steer what is written where.
- Every session made here is tagged with its run's marker, which the local file keeps. A logout deletes the
  sessions of the runs in OUT by that tag, the ones Odoo renamed since (it rotates a session's id after a few
  hours) included; `logout --all` deletes every tagged session on the build, leftovers of crashed runs too. A
  session without the tag is never deleted.
- A logout keeps the local files when the build did not confirm every deletion, so it can be run again.
- `ssh` forwards nothing to the build, no agent, no X11, no port: the build runs a branch's code.
"""

import json
import os
import re
import secrets
import subprocess
from pathlib import Path
from typing import Annotated

import typer

import shpilot
from shpilot.cli._client import open_client
from shpilot.cli._context import BranchOption, ProjectOption, find_build, project_branch, resolve_branch
from shpilot.cli._output import strip_control
from shpilot.cli.ssh import reach


app = typer.Typer(
    name="web-session",
    help="Log a test browser into a staging or development build as any user, with no password, and out again.",
    no_args_is_help=True,
    epilog="Example: shpilot web-session login --branch staging --out ./sessions admin",
)

EXIT_REFUSED = 9
EXIT_NOT_DONE = 1
TAG = "shpilot_web_session"
"""The key every session made here carries in the build's session store."""

_SID = re.compile(r"[A-Za-z0-9_-]{32,128}")
# No agent, X11 or port forwarding: the build runs a branch's code, and must not reach the user's keys.
_SSH = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "IPQoS=none",
        "-o", "ForwardAgent=no", "-o", "ForwardX11=no", "-o", "ClearAllForwardings=yes"]
_SHELL = "timeout 300 odoo-bin shell --no-http --log-level=error"

OutOption = Annotated[
    Path,
    typer.Option("--out", help="The directory the session files go to, one per user, readable by you alone.",
                 show_default=False),
]
YesOption = Annotated[
    bool,
    typer.Option("--yes", "-y", help="Allow this machine's address for SSH without asking, when it is kept out."),
]

_LOGIN = """
import json
from odoo import http
from odoo.http import root
MARK, TAG, RUN = {mark!r}, {tag!r}, {run!r}
done = set()
for key in json.loads({keys!r}):
    users = env['res.users'].with_context(active_test=False)
    user = users.browse(int(key)) if key.isdigit() else users.search([('login', '=', key)], limit=1)
    if not user.exists() or not user.active:
        print(MARK, json.dumps({{'error': 'no active user', 'key': key}}))
        continue
    if user.id in done:
        continue
    done.add(user.id)
    session = root.session_store.new()
    session.update(http.get_default_session())
    session.update(db=env.cr.dbname, uid=user.id, login=user.login,
                   context={{'lang': user.lang or 'en_US', 'tz': user.tz or 'UTC', 'uid': user.id}})
    session[TAG] = RUN
    session.session_token = user._compute_session_token(session.sid)
    root.session_store.save(session)
    print(MARK, json.dumps({{'uid': user.id, 'login': user.login, 'db': env.cr.dbname, 'sid': session.sid}}))
"""

_LOGOUT = """
import json, os
from odoo.http import root
MARK, TAG = {mark!r}, {tag!r}
store = root.session_store
runs = set(json.loads({runs!r}))
names = set()
# Odoo keeps each session in a folder named after the start of its id, which `store.list()` does not walk.
for _folder, _dirs, files in os.walk(store.path):
    names.update(name for name in files if store.is_valid_key(name))

def ours(session):
    tag = session.get(TAG)
    return bool(tag) and ({everything!r} or tag in runs)

deleted = 0
for sid in names:
    session = store.get(sid)
    if ours(session):
        store.delete(session)
        deleted += 1
left = sum(1 for sid in names if os.path.exists(store.get_session_filename(sid)) and ours(store.get(sid)))
print(MARK, json.dumps({{'deleted': deleted, 'left': left}}))
"""


def _target(ctx: typer.Context, project: str | None, branch: str | None, *, yes: bool) -> tuple[str, shpilot.SshTarget]:
    """Return the build's URL and where `ssh` reaches it, refusing production and a stage not known."""
    name = resolve_branch(ctx, branch)
    with open_client() as client:
        project_name, found = project_branch(ctx, client, project, name)
        if found.stage not in (shpilot.Stage.STAGING, shpilot.Stage.DEVELOPMENT):
            typer.echo(strip_control(
                f"Refused: {found.name} of {project_name} is a {found.stage_name} branch. Sessions are made on staging "
                "and development builds only."
            ), err=True)
            raise typer.Exit(EXIT_REFUSED)
        target = client.ssh_target(find_build(client, project_name, found, None))
    again = f"shpilot web-session ... --project {project_name} --branch {found.name}"
    reach(ctx, found, target, "ssh", yes=yes, again=again)
    return f"https://{target.host}", target


def _remote(target: shpilot.SshTarget, script: str, mark: str) -> list[dict[str, object]]:
    """Run `script` in `odoo-bin shell` on the build, and return the JSON objects of the lines carrying `mark`."""
    command = [*_SSH, "-l", target.user, target.host, _SHELL]
    done = subprocess.run(command, input=script, capture_output=True, text=True, check=False, timeout=360)  # noqa: S603
    found: list[dict[str, object]] = []
    for line in done.stdout.splitlines():
        head, _, body = line.partition(" ")
        if head != mark:
            continue
        try:
            value = json.loads(body)
        except ValueError:
            continue
        if isinstance(value, dict):
            found.append(value)
    if done.returncode != 0 and not found:
        last = (done.stderr.strip().splitlines() or ["no output"])[-1]
        typer.echo(strip_control(f"The build did not run the session script: {last}"), err=True)
        raise typer.Exit(EXIT_NOT_DONE)
    return found


@app.command(epilog="Example: shpilot web-session login --branch staging --out ./sessions admin 7")
def login(
    ctx: typer.Context,
    users: Annotated[list[str], typer.Argument(help="Logins or user ids, one session each.", show_default=False)],
    out: OutOption,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    yes: YesOption = False,
) -> None:
    """Make a web session on the build for each USER, and write it to OUT/<uid>.session (url, db, uid, login, sid).

    The session id is never printed. Use it from a test browser, then `shpilot web-session logout`. Production is
    refused (exit 9).
    """
    url, target = _target(ctx, project, branch, yes=yes)
    if not out.exists():
        out.mkdir(parents=True, mode=0o700)
    mark, run = secrets.token_hex(12), secrets.token_hex(12)
    script = _LOGIN.format(mark=mark, tag=TAG, run=run, keys=json.dumps(list(dict.fromkeys(users))))
    written = 0
    for item in _remote(target, script, mark):
        if "error" in item:
            typer.echo(strip_control(f"No session for {item.get('key')}: {item['error']}."), err=True)
            continue
        uid, sid, login_name = item.get("uid"), item.get("sid"), item.get("login")
        if not isinstance(uid, int) or not isinstance(sid, str) or not _SID.fullmatch(sid):
            typer.echo("The build answered something that is not a session; it was ignored.", err=True)
            continue
        path = out / f"{uid}.session"
        _write_private(path, {"url": url, "db": item.get("db"), "uid": uid, "login": login_name, "sid": sid, "run": run})
        written += 1
        typer.echo(strip_control(f"Session for {login_name} (uid {uid}): {path}"), err=True)
    if written < len(dict.fromkeys(users)):
        raise typer.Exit(EXIT_NOT_DONE)


def _write_private(path: Path, data: dict[str, object]) -> None:
    """Write a file only the user can read, never through a link, whatever was there before."""
    if path.is_symlink():
        # Also checked where the system has no O_NOFOLLOW (Windows).
        msg = f"{path} is a link: refusing to write a session through it."
        raise OSError(msg)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        if hasattr(os, "fchmod"):
            os.fchmod(file.fileno(), 0o600)
        file.write(json.dumps(data))


@app.command(epilog="Example: shpilot web-session logout --branch staging --out ./sessions")
def logout(
    ctx: typer.Context,
    out: OutOption,
    project: ProjectOption = None,
    branch: BranchOption = None,
    *,
    everything: Annotated[
        bool,
        typer.Option("--all", help="Also delete every other session shpilot made on this build: renamed or left over."),
    ] = False,
    yes: YesOption = False,
) -> None:
    """Delete on the build the sessions written to OUT, then the files. Keeps the files when the build did not confirm."""
    files = sorted(out.glob("*.session")) if out.is_dir() else []
    runs: list[str] = []
    for path in files:
        try:
            run = json.loads(path.read_text()).get("run")
        except (OSError, ValueError):
            continue
        if isinstance(run, str) and re.fullmatch(r"[0-9a-f]{24}", run) and run not in runs:
            runs.append(run)
    if not runs and not everything:
        typer.echo(strip_control(f"No session file in {out}: nothing to log out."), err=True)
        return
    _, target = _target(ctx, project, branch, yes=yes)
    mark = secrets.token_hex(12)
    script = _LOGOUT.format(mark=mark, tag=TAG, runs=json.dumps(runs), everything=everything)
    answers = _remote(target, script, mark)
    answer = answers[0] if answers else {}
    deleted, left = answer.get("deleted"), answer.get("left")
    if not isinstance(deleted, int) or left != 0:
        typer.echo(strip_control(
            f"The build did not confirm every session was deleted; the files in {out} are kept. Run it again, "
            "or with --all."
        ), err=True)
        raise typer.Exit(EXIT_NOT_DONE)
    for path in files:
        path.unlink(missing_ok=True)
    typer.echo(f"Deleted {deleted} session(s) on the build.", err=True)

