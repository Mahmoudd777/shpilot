"""`shpilot projects`: the Odoo.sh projects the session's user can reach, one's overview, settings, checks, audit log and
members, and the changes of its settings and members.
"""

import ipaddress
from collections.abc import Callable, Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import takewhile
from typing import Annotated

import typer

import shpilot
from shpilot.cli import _settings, _size, _terminal
from shpilot.cli import _guard
from shpilot.cli._client import open_client
from shpilot.cli._context import ProjectOption, resolve_project, result_of, status_of
from shpilot.cli._errors import EXIT_CHECK_FAILED, EXIT_CHECK_WARNED, EXIT_DECLINED
from shpilot.cli._output import Column, Output, strip_control
from shpilot.cli._settings import quoted, shown


app = typer.Typer(
    name="projects",
    help="List the Odoo.sh projects you can reach, show one's overview, show and change its settings, check it, "
    "read its audit log, and list its members, add one and change one's role.",
    epilog="Example: shpilot projects list",
    no_args_is_help=True,
)
settings_app = typer.Typer(
    name="settings",
    help="Show a project's settings, or change them.",
    epilog="Example: shpilot projects settings show --project acme-shop",
    no_args_is_help=True,
)
app.add_typer(settings_app)
members_app = typer.Typer(
    name="members",
    help="List a project's members, add one, or change one's role.",
    epilog="Example: shpilot projects members list --project acme-shop",
    no_args_is_help=True,
)
app.add_typer(members_app)

_COLUMNS = [
    Column[shpilot.Project]("Name", lambda project: project.name),
    Column[shpilot.Project]("Repository", lambda project: project.repository),
    Column[shpilot.Project]("URL", lambda project: project.url),
]

_ADMINS_ONLY = "admins only"
_SUBSCRIPTION_STYLES = {
    shpilot.Subscription.VALID: "green",
    shpilot.Subscription.TRIAL: "yellow",
    shpilot.Subscription.NON_STANDARD: "yellow",
    shpilot.Subscription.EXPIRED: "red",
}

StorageMarginOption = Annotated[
    int,
    typer.Option(
        "--storage-margin",
        min=0,
        max=100,
        metavar="PERCENT",
        help="Warn when the storage used is within this share of the quota. 0 never warns, 100 warns on any use.",
    ),
]


@app.command("list", epilog="Example: shpilot projects list")
def list_(ctx: typer.Context) -> None:
    """List the projects you can reach, with their repository and address."""
    output: Output = ctx.obj

    with open_client() as client:
        found = client.projects()

    output.rows(found, _COLUMNS, empty="No projects.")


@app.command(epilog="Example: shpilot projects show --project acme-shop")
def show(ctx: typer.Context, project: ProjectOption = None) -> None:
    """Show a project's overview, one fact per line: its subscription, Odoo version, hosting, production build and branches by stage.

    Storage, workers and staging branches are on the project's Settings page, which Odoo.sh shows to an admin of the project only: anyone else gets `admins only`.
    """
    output: Output = ctx.obj

    with open_client() as client:
        read = client.project_overview(resolve_project(ctx, project, client.projects))

    output.one(read, _OVERVIEW)


@settings_app.command("show", epilog="Example: shpilot projects settings show --project acme-shop")
def settings_show(ctx: typer.Context, project: ProjectOption = None) -> None:
    """Show a project's settings, one per line, as its Settings page has them.

    Odoo.sh shows them to an admin of the project only: anyone else gets exit code 5. The rows from `Dev install` to `Dev AI agent` are the defaults of new development branches. A submodule's public deploy key is in `--format json` only.
    """
    output: Output = ctx.obj

    with open_client() as client:
        read = client.project_settings(resolve_project(ctx, project, client.projects))

    output.one(read, _SETTINGS)


# How a setting given on the command line is read, by its name in `ProjectSettings`.
_READS: dict[str, _settings.Read] = {
    "session_lifetime": _settings.choice(shpilot.SessionLifetime),
    "public": _settings.flag,
    "http_timeout_seconds": _settings.seconds,
    "cron_timeout_seconds": _settings.seconds,
    "module_install": _settings.choice(shpilot.ModuleInstall),
    "modules": _settings.names,
    "tests": _settings.choice(shpilot.BuildTests),
    "test_tags": _settings.text,
    "demo_data": _settings.flag,
    "ai_agent": _settings.choice(shpilot.AiAgent),
}
_ALLOW_LIST = "ip_allow_list"
_REFUSED = {_ALLOW_LIST: "The allow list is not given whole: give --add-ip or --remove-ip for each entry."}
_ENTRIES = frozenset({"allow_ips", "disallow_ips"})

SettingsArgument = Annotated[
    list[str] | None,
    typer.Argument(
        metavar="[NAME=VALUE]...",
        show_default=False,
        help="A setting and its new value, named as `shpilot projects settings show --format json` prints them.",
    ),
]
AddIpOption = Annotated[
    list[str] | None,
    typer.Option(
        "--add-ip",
        metavar="IP",
        help="An IPv4 address to add to the IP allow list. Can be given more than once.",
    ),
]
RemoveIpOption = Annotated[
    list[str] | None,
    typer.Option(
        "--remove-ip",
        metavar="ENTRY",
        help="An address or a network to remove from the IP allow list, as `shpilot projects settings show` lists it. "
        "Can be given more than once.",
    ),
]


@settings_app.command("set", epilog="Example: shpilot projects settings set --project acme-shop --add-ip 203.0.113.7")
def settings_set(
    ctx: typer.Context,
    settings: SettingsArgument = None,
    project: ProjectOption = None,
    *,
    add_ip: AddIpOption = None,
    remove_ip: RemoveIpOption = None,
    yes: _settings.YesOption = False,
) -> None:
    """Change state on Odoo.sh: change a project's settings, sending only those given.

    The others keep their value. NAME is one of session_lifetime, public, http_timeout_seconds, cron_timeout_seconds, module_install, modules, tests, test_tags, demo_data and ai_agent, the last six being the defaults of new development branches. A choice takes a value `show --format json` prints, a yes or no takes `yes` or `no`, a timeout takes seconds, a multiple of 60, and is changed on a dedicated server only, `modules` takes names separated by commas, and `test_tags=` clears the tags. The IP allow list, which SSH and PostgreSQL to production and staging go through, is changed by entry with `--add-ip` and `--remove-ip`, ten entries at most. Only an admin of the project can change them: anyone else gets exit code 5. It asks first, saying when the change is to who can reach the project, unless `--yes` is given.
    """
    output: Output = ctx.obj
    change = _project_change(ctx, settings or [], add_ip or [], remove_ip or [])
    _settings.can_ask(ctx, yes=yes)

    with open_client(writes=True) as client:
        name = resolve_project(ctx, project, client.projects)
        _guard.require(name, "Change the project's settings or its IP allow list.")
        current = client.project_settings(name)
        narrowed = _settings.checked(ctx, lambda: client.check_project_settings_change(current, change))

        for line in _changing(name, current, change, narrowed):
            _settings.say(line)

        if narrowed is None:
            typer.echo("Nothing was sent: every setting already has that value.", err=True)
            output.one(current, _SETTINGS)

            return

        for line in _access(current, narrowed):
            _settings.say(line)

        question = (
            "Change these settings of this project, including access?"
            if narrowed.access()
            else ("Change these settings of this project?")
        )

        if not yes and not _terminal.confirmed(question):
            typer.echo("Nothing was sent.", err=True)
            raise typer.Exit(EXIT_DECLINED)

        # Sent once: an error is reported, never retried.
        outcome = _settings.checked(ctx, lambda: client.change_project_settings(name, narrowed))
        typer.echo("The settings were changed.", err=True)
        _settings.say_moved(outcome)

    output.one(outcome.after, _SETTINGS)


def _project_change(
    ctx: typer.Context, pairs: list[str], added: list[str], removed: list[str]
) -> shpilot.ProjectSettingsChange:
    """Read the settings and the entries given into the change they make, refusing what the library would."""
    values = _settings.given(ctx, pairs, _READS, _REFUSED)
    allow = tuple(_address(ctx, text) for text in added)
    disallow = tuple(_entry(ctx, text) for text in removed)

    # Each part on its own first, so that an error names the option or the argument at fault.
    if allow:
        _settings.built(ctx, lambda: shpilot.ProjectSettingsChange(allow_ips=allow), "--add-ip")

    if disallow:
        _settings.built(ctx, lambda: shpilot.ProjectSettingsChange(disallow_ips=disallow), "--remove-ip")

    if values:
        _settings.built(ctx, lambda: shpilot.ProjectSettingsChange(**values))  # pyright: ignore[reportArgumentType]

    return _settings.built(
        ctx,
        lambda: shpilot.ProjectSettingsChange(
            **values,  # pyright: ignore[reportArgumentType]
            allow_ips=allow or None,
            disallow_ips=disallow or None,
        ),
        "--add-ip, --remove-ip" if allow and disallow else _settings.PARAM,
    )


def _address(ctx: typer.Context, text: str) -> ipaddress.IPv4Address:
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        msg = f"{text!r} is not an IP address."
        raise typer.BadParameter(msg, ctx=ctx, param_hint="--add-ip") from None

    if not isinstance(address, ipaddress.IPv4Address):
        msg = f"{text} is not an IPv4 address: the allow list takes those one by one, as its page does."
        raise typer.BadParameter(msg, ctx=ctx, param_hint="--add-ip")

    return address


def _entry(
    ctx: typer.Context, text: str
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | ipaddress.IPv4Network | ipaddress.IPv6Network:
    # Read as `show` lists an entry: with a `/` as a network, otherwise as an address.
    try:
        return ipaddress.ip_network(text, strict=False) if "/" in text else ipaddress.ip_address(text)
    except ValueError:
        msg = f"{text!r} is not an address or a network."
        raise typer.BadParameter(msg, ctx=ctx, param_hint="--remove-ip") from None


def _changing(
    project: str,
    current: shpilot.ProjectSettings,
    change: shpilot.ProjectSettingsChange,
    narrowed: shpilot.ProjectSettingsChange | None,
) -> list[str]:
    """Say what a change is about to work on: the project, and each setting from its value to the new one.

    A setting is already at its value, and an entry already allowed or not listed, when the library
    leaves it out of what it sends.
    """
    sent = {} if narrowed is None else narrowed.given()
    lines = [f"Project: {project}"]

    for name, value in change.given().items():
        if name not in _ENTRIES:
            before, after = quoted(getattr(current, name)), quoted(value)
            lines.append(f"{name}: {before} → {after}" if name in sent else f"{name} is already {after}.")

    return lines + _allow_list_changing(current, change, narrowed)


def _allow_list_changing(
    current: shpilot.ProjectSettings,
    change: shpilot.ProjectSettingsChange,
    narrowed: shpilot.ProjectSettingsChange | None,
) -> list[str]:
    """Say what a change is about to do to the allow list, and which of its entries it leaves as they are."""
    allowed = () if narrowed is None else narrowed.allow_ips or ()
    removed = () if narrowed is None else narrowed.disallow_ips or ()
    lines: list[str] = []

    if allowed or removed:
        lines.append(f"{_ALLOW_LIST}: {shown(current.ip_allow_list)} → {shown(_listed(current, allowed, removed))}")

    lines.extend(f"{address} is already allowed." for address in change.allow_ips or () if address not in allowed)
    lines.extend(f"{entry} is not in the list." for entry in change.disallow_ips or () if entry not in removed)

    return lines


def _access(current: shpilot.ProjectSettings, narrowed: shpilot.ProjectSettingsChange) -> list[str]:
    """Say what a change does to who can reach the project, before the question."""
    access = narrowed.access()

    if not access:
        return []

    named = dict.fromkeys(_ALLOW_LIST if name in _ENTRIES else name for name in access)
    lines = [f"This changes who can reach the project: {', '.join(named)}."]
    removed = narrowed.disallow_ips or ()

    if removed:
        lines.append(
            f"SSH to production and staging from {shown(removed)} then needs the one-hour rule `shpilot ssh` asks for. "
            f"PostgreSQL on a dedicated server is then closed to {shown(removed)}."
        )

    if (removed or narrowed.allow_ips) and not _listed(current, narrowed.allow_ips or (), removed):
        lines.append("The allow list will be empty: no address keeps a permanent rule.")

    return lines


def _listed(
    current: shpilot.ProjectSettings, allowed: tuple[object, ...], removed: tuple[object, ...]
) -> tuple[object, ...]:
    """Return the allow list as it is to be after a change."""
    return (*(entry for entry in current.ip_allow_list if entry not in removed), *allowed)


_AUDIT_LIMIT = 20
_MAX_AUDIT_LIMIT = 200
# Two requests: the project's info, then its whole log.
_AUDIT_TIMEOUT = 60.0
_LOGGED = "%Y-%m-%d %H:%M:%S"

AuditLimitOption = Annotated[
    int,
    typer.Option("--limit", min=1, max=_MAX_AUDIT_LIMIT, help=f"The most entries to list, {_MAX_AUDIT_LIMIT} at most."),
]
SinceOption = Annotated[
    datetime | None,
    typer.Option(
        "--since",
        formats=["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"],
        metavar="DATE",
        help="List only the entries at or after this moment, in UTC, such as 2026-10-01 or 2026-10-01T09:30:00.",
    ),
]


def _untrusted(text: str) -> str:
    """Put text others wrote on one line, without its escape sequences."""
    return shpilot.strip_line_control(" ".join(text.splitlines()))


def _action(entry: shpilot.AuditEntry) -> str:
    named = _untrusted(entry.kind_name) if entry.kind is shpilot.AuditKind.UNKNOWN else entry.kind.value
    return named if entry.succeeded else f"{named} (failed)"


_AUDIT_COLUMNS = [
    Column[shpilot.AuditEntry]("Date (UTC)", lambda entry: entry.logged_at.strftime(_LOGGED)),
    Column[shpilot.AuditEntry]("By", lambda entry: _untrusted(entry.author)),
    Column[shpilot.AuditEntry]("Stage", lambda entry: "project" if entry.stage is None else entry.stage.value),
    Column[shpilot.AuditEntry]("Action", _action),
    Column[shpilot.AuditEntry]("Details", lambda entry: _untrusted(entry.details)),
]


@app.command(epilog="Example: shpilot projects audit --limit 10")
def audit(
    ctx: typer.Context,
    project: ProjectOption = None,
    *,
    limit: AuditLimitOption = _AUDIT_LIMIT,
    since: SinceOption = None,
) -> None:
    """List a project's audit log, newest first: who did what, when, on which stage, and what Odoo.sh adds about it.

    Odoo.sh sends the last 30 days in one answer, and shows the log to an admin of the project only: anyone else gets exit code 5. Nothing older than 30 days can be read, whatever `--since` says.
    """
    output: Output = ctx.obj
    start = None if since is None else since.replace(tzinfo=UTC)
    # With `--since`, one more tells whether the limit left out entries the date asked for.
    asked = limit if start is None else limit + 1

    with open_client() as client:
        name = resolve_project(ctx, project, client.projects)

        # Closed on leaving, so the first entry older than `start` is the last one read.
        with closing(client.audit_log(name, limit=asked, timeout=_AUDIT_TIMEOUT)) as read:
            found = list(read if start is None else takewhile(lambda entry: entry.logged_at >= start, read))

    output.rows(found[:limit], _AUDIT_COLUMNS, empty="No audit log entries.")

    if start is not None and len(found) > limit:
        more = f"raise --limit, up to {_MAX_AUDIT_LIMIT}" if limit < _MAX_AUDIT_LIMIT else "give a later --since"
        typer.echo(
            f"Showing the newest {limit} entries: older ones since {start.strftime(_LOGGED)} UTC were left out. "
            f"To see them, {more}.",
            err=True,
        )


_MEMBER_COLUMNS = [
    Column[shpilot.ProjectMember]("Login", lambda member: _untrusted(member.login)),
    Column[shpilot.ProjectMember]("Name", lambda member: _untrusted(member.name)),
    Column[shpilot.ProjectMember]("Role", lambda member: member.role.value),
    Column[shpilot.ProjectMember]("Logged in", lambda member: "no" if member.pending_login else "yes"),
]


LoginArgument = Annotated[
    str, typer.Argument(metavar="LOGIN", show_default=False, help="The GitHub login of the user.")
]
MemberArgument = Annotated[
    str,
    typer.Argument(metavar="LOGIN", show_default=False, help="The member's login, as `list` prints it, in any case."),
]
RoleArgument = Annotated[
    shpilot.MemberRole, typer.Argument(metavar="ROLE", show_default=False, help="The member's new role.")
]
RoleOption = Annotated[shpilot.MemberRole, typer.Option("--role", help="The new member's role.")]

# What a role reaches, as the page's add dialog lists it.
_REACH = {
    shpilot.MemberRole.ADMIN: "An admin reaches production: its database, shell and logs, and the project's settings.",
    shpilot.MemberRole.TESTER: "A tester reaches staging, not production.",
    shpilot.MemberRole.DEVELOPER: "A developer reaches development branches only.",
}


@members_app.command("list", epilog="Example: shpilot projects members list --project acme-shop")
def members_list(ctx: typer.Context, project: ProjectOption = None) -> None:
    """List a project's members with their role, highest role first, then by login.

    Odoo.sh lists them to an admin of the project only: anyone else gets exit code 5. `Logged in` is `no` for a member invited who has not logged in to Odoo.sh yet. It changes nothing.
    """
    output: Output = ctx.obj

    with open_client() as client:
        found = client.members(resolve_project(ctx, project, client.projects))

    output.rows(sorted(found, key=_member_order), _MEMBER_COLUMNS, empty="No members.")


def _member_order(member: shpilot.ProjectMember) -> tuple[int, str, str]:
    return -member.role.rank, member.login.casefold(), member.login


@members_app.command("add", epilog="Example: shpilot projects members add octo-cat --role tester --project acme-shop")
def members_add(
    ctx: typer.Context,
    login: LoginArgument,
    role: RoleOption = shpilot.MemberRole.DEVELOPER,
    project: ProjectOption = None,
    *,
    yes: _settings.YesOption = False,
) -> None:
    """Change state on Odoo.sh: add a GitHub user to a project's members, as a developer unless `--role` says otherwise.

    Odoo.sh sends them no invitation, and push access to the repository is given on GitHub. Only an admin of the project can add one: anyone else gets exit code 5, as does a session whose grant on GitHub does not cover the search of users, until a user is searched once in the Collaborators item of the project's Settings page. A login GitHub does not have exits 4, and a user already a member exits 9, both with nothing sent. It asks first, unless `--yes` is given.
    """
    output: Output = ctx.obj

    try:
        shpilot.Client.check_add_member(login, role)
    except ValueError as error:
        raise typer.BadParameter(str(error), ctx=ctx, param_hint="LOGIN") from None

    _settings.can_ask(ctx, yes=yes)

    with open_client(writes=True) as client:
        name = resolve_project(ctx, project, client.projects)
        _guard.require(name, f"Add {login} to the project as {role}.")
        client.check_add_member(login, role, client.members(name))

        for line in (
            f"Project: {name}",
            f"Member: {login}",
            f"Role: {role.value}",
            _REACH[role],
            "Odoo.sh sends them no invitation, and push access to the repository is given on GitHub.",
        ):
            _settings.say(line)

        if not yes and not _terminal.confirmed(strip_control(f"Add {login} to {name} as {role.value}?")):
            typer.echo("Nothing was sent.", err=True)
            raise typer.Exit(EXIT_DECLINED)

        # Sent once: an error is reported, never retried.
        added = client.add_member(name, login, role)

    _settings.say(f"{added.login} is now a member of {name}, as {added.role.value}.")
    output.one(added, _MEMBER_COLUMNS)


@members_app.command("role", epilog="Example: shpilot projects members role jane-doe developer --project acme-shop")
def members_role(
    ctx: typer.Context,
    login: MemberArgument,
    role: RoleArgument,
    project: ProjectOption = None,
    *,
    yes: _settings.YesOption = False,
) -> None:
    """Change state on Odoo.sh: give a member of a project another role.

    Only an admin of the project can change one: anyone else gets exit code 5. A login that is not a member exits 4, and lowering the last admin who has logged in to Odoo.sh exits 9, both with nothing sent. A member who already has the role exits 0 with nothing sent. It asks first, unless `--yes` is given.
    """
    output: Output = ctx.obj
    _settings.can_ask(ctx, yes=yes)

    with open_client(writes=True) as client:
        name = resolve_project(ctx, project, client.projects)
        _guard.require(name, f"Give {login} the role {role}.")
        current = client.members(name)
        found = client.check_member_role(current, login, role)

        if found.role is role:
            _settings.say(f"{found.login} is already {role.value} on {name}. Nothing was sent.")
            output.one(found, _MEMBER_COLUMNS)

            return

        lines = [f"Project: {name}", f"Member: {found.login}", f"Role: {found.role.value} → {role.value}", _REACH[role]]

        # Any other role is lower: `found` does not have `role`.
        if found.role is shpilot.MemberRole.ADMIN and _is_caller(client, found):
            lines.append("This is you: you will not be able to change it back.")

        for line in lines:
            _settings.say(line)

        question = f"Change {found.login}'s role on {name} to {role.value}?"

        if not yes and not _terminal.confirmed(strip_control(question)):
            typer.echo("Nothing was sent.", err=True)
            raise typer.Exit(EXIT_DECLINED)

        # Sent once: an error is reported, never retried.
        changed = client.set_member_role(name, found, role)

    _settings.say(f"{changed.login} is now {changed.role.value} on {name}.")
    output.one(changed, _MEMBER_COLUMNS)


def _is_caller(client: shpilot.Client, member: shpilot.ProjectMember) -> bool:
    return client.identity().username.casefold() == member.login.casefold()


class Verdict(StrEnum):
    """The result of one check of `shpilot projects check`."""

    PASSED = "pass"
    WARNED = "warn"
    FAILED = "fail"
    SKIPPED = "skip"
    """The check could not be made. It does not count in the exit code."""


@dataclass(frozen=True, slots=True)
class Check:
    """One check of a project: what it looked at, its result, and the fact it was judged on."""

    name: str
    """What scripts match on, so renaming one is a breaking change."""
    result: Verdict
    fact: str


_VERDICT_STYLES = {Verdict.PASSED: "green", Verdict.WARNED: "yellow", Verdict.FAILED: "red"}

_CHECK_COLUMNS = [
    Column[Check]("Check", lambda check: check.name),
    Column[Check]("Result", lambda check: check.result.value, lambda check: _VERDICT_STYLES.get(check.result)),
    Column[Check]("Fact", lambda check: check.fact),
]


@app.command(epilog="Example: shpilot projects check --project acme-shop")
def check(ctx: typer.Context, project: ProjectOption = None, storage_margin: StorageMarginOption = 10) -> None:
    """Check a project's subscription, production build, storage and branches, and exit 30 when one fails, 31 when one warns.

    Each check is a row: its name, `pass`, `warn`, `fail` or `skip`, and the fact it was judged on. Storage is on the project's Settings page, which Odoo.sh shows to an admin of the project only: anyone else gets `skip`, which does not count in the exit code.
    """
    output: Output = ctx.obj

    with open_client() as client:
        read = client.project_overview(resolve_project(ctx, project, client.projects))

    checks = _checks(read, margin=storage_margin)
    output.rows(checks, _CHECK_COLUMNS, empty="")
    code = _exit_code(checks)

    if code:
        raise typer.Exit(code)


def _checks(read: shpilot.ProjectOverview, *, margin: int) -> tuple[Check, ...]:
    return (
        _check_subscription(read),
        _check_production(read),
        _check_storage(read, margin),
        _check_branches(read),
    )


def _exit_code(checks: Iterable[Check]) -> int:
    worst = _worst(check.result for check in checks)
    return {Verdict.FAILED: EXIT_CHECK_FAILED, Verdict.WARNED: EXIT_CHECK_WARNED}.get(worst, 0)


def _worst(verdicts: Iterable[Verdict]) -> Verdict:
    found = set(verdicts)
    return next((verdict for verdict in (Verdict.FAILED, Verdict.WARNED) if verdict in found), Verdict.PASSED)


def _check_subscription(read: shpilot.ProjectOverview) -> Check:
    # The project's page calls any state it does not know an invalid subscription.
    if read.subscription in {shpilot.Subscription.EXPIRED, shpilot.Subscription.UNKNOWN}:
        result = Verdict.FAILED
    elif read.subscription is shpilot.Subscription.VALID and read.trial_days_left is None:
        result = Verdict.PASSED
    else:
        result = Verdict.WARNED

    return Check("subscription", result, _subscription(read))


def _check_production(read: shpilot.ProjectOverview) -> Check:
    judged = [_last_build(summary) for summary in read.branches if summary.branch.stage is shpilot.Stage.PRODUCTION]

    if not judged:
        return Check("production", Verdict.WARNED, "no production branch")

    return Check("production", _worst(result for result, _ in judged), "; ".join(fact for _, fact in judged))


_SAID = {
    shpilot.BuildResult.SUCCESS: (Verdict.PASSED, "succeeded"),
    shpilot.BuildResult.WARNING: (Verdict.WARNED, "finished with warnings"),
    shpilot.BuildResult.FAILED: (Verdict.FAILED, "failed"),
}
_RUNNING = frozenset({shpilot.BuildStatus.PROGRESS, shpilot.BuildStatus.UPDATING})


def _last_build(summary: shpilot.BranchSummary) -> tuple[Verdict, str]:
    """Judge a branch's last build by its result, so a build dropped for a newer one counts as it ended."""
    build = summary.last_build

    if build is None:
        return Verdict.WARNED, f"{summary.branch.name} has no build"

    if build.result is None and build.status in _RUNNING:
        result, said = Verdict.WARNED, f"has no result yet ({status_of(build)})"
    elif build.result is None:
        result, said = Verdict.WARNED, f"ended without a result ({status_of(build)})"
    else:
        result, said = _SAID.get(build.result) or (Verdict.WARNED, f"ended {result_of(build)}")

    return result, f"build {build.id} on {summary.branch.name} {said}"


def _check_storage(read: shpilot.ProjectOverview, margin: int) -> Check:
    hosting = read.hosting

    if hosting is None:
        return Check("storage", Verdict.SKIPPED, _ADMINS_ONLY)

    used, quota = hosting.storage_used_bytes, hosting.storage_quota_bytes

    if not quota:
        result = Verdict.SKIPPED
    elif used >= quota:
        result = Verdict.FAILED
    # In integers, so no rounding moves the boundary.
    elif used * 100 > quota * (100 - margin):
        result = Verdict.WARNED
    else:
        result = Verdict.PASSED

    return Check("storage", result, _storage(hosting))


def _check_branches(read: shpilot.ProjectOverview) -> Check:
    # An unknown result could be a failure Odoo.sh renamed, so it warns rather than passing as none failed.
    flagged = [
        _last_build(summary)
        for summary in read.branches
        if summary.last_build is not None
        and summary.last_build.result in {shpilot.BuildResult.FAILED, shpilot.BuildResult.UNKNOWN}
    ]

    if flagged:
        return Check("branches", _worst(result for result, _ in flagged), ", ".join(fact for _, fact in flagged))

    count = len(read.branches)

    return Check("branches", Verdict.PASSED, f"{count} branch{'' if count == 1 else 'es'}, none failed")


def _subscription(read: shpilot.ProjectOverview) -> str:
    named = read.subscription_name if read.subscription is shpilot.Subscription.UNKNOWN else read.subscription.value
    days = read.trial_days_left

    return named if days is None else f"{named}, {days} day{'' if days == 1 else 's'} left"


def _hosting(value: Callable[[shpilot.ProjectHosting], object]) -> Callable[[shpilot.ProjectOverview], object]:
    return lambda read: _ADMINS_ONLY if read.hosting is None else value(read.hosting)


def _storage(hosting: shpilot.ProjectHosting) -> str:
    shown = f"{_size.size(hosting.storage_used_bytes)} of {_size.size(hosting.storage_quota_bytes)}"

    if not hosting.storage_quota_bytes:
        return shown

    return f"{shown}, {hosting.storage_used_bytes * 100 / hosting.storage_quota_bytes:.0f}%"


def _production(read: shpilot.ProjectOverview) -> str:
    build = read.production_build
    return "none" if build is None else f"{build.id} on {build.branch_name}"


def _stages(read: shpilot.ProjectOverview) -> str:
    return ", ".join(
        f"{counted.count} {counted.stage_name if counted.stage is shpilot.Stage.UNKNOWN else counted.stage.value}"
        for counted in read.stages
    )


_OVERVIEW = [
    Column[shpilot.ProjectOverview]("Name", lambda read: read.name),
    Column[shpilot.ProjectOverview]("Repository", lambda read: read.repository),
    Column[shpilot.ProjectOverview](
        "Subscription", _subscription, lambda read: _SUBSCRIPTION_STYLES.get(read.subscription)
    ),
    Column[shpilot.ProjectOverview]("Odoo version", lambda read: read.odoo_version),
    Column[shpilot.ProjectOverview]("Region", lambda read: read.region),
    Column[shpilot.ProjectOverview]("Storage", _hosting(_storage)),
    Column[shpilot.ProjectOverview]("Workers", _hosting(lambda hosting: hosting.workers)),
    Column[shpilot.ProjectOverview]("Staging branches", _hosting(lambda hosting: hosting.staging_branches)),
    Column[shpilot.ProjectOverview]("Dedicated", lambda read: "yes" if read.dedicated else "no"),
    Column[shpilot.ProjectOverview]("Production build", _production),
    Column[shpilot.ProjectOverview](
        "Production URL", lambda read: None if read.production_build is None else read.production_build.url
    ),
    Column[shpilot.ProjectOverview]("Branches", _stages),
    Column[shpilot.ProjectOverview]("Your access", lambda read: read.access_level),
]


def _minutes(seconds: int) -> str:
    # In minutes, as the Settings page shows them.
    minutes = seconds / 60
    return f"{minutes:g} minute{'' if minutes == 1 else 's'}"


def _submodules(read: shpilot.ProjectSettings) -> str:
    # An empty URL is one the library could not read without what may be part of a password.
    listed = (f"{shown(_untrusted(sub.url))} ({_untrusted(sub.fingerprint)})" for sub in read.submodules)
    return ", ".join(listed) or "none"


_SETTINGS = [
    Column[shpilot.ProjectSettings]("Name", lambda read: read.name),
    Column[shpilot.ProjectSettings]("odoo.com domain blocked", lambda read: shown(read.odoo_domain_blocked)),
    Column[shpilot.ProjectSettings]("Session lifetime", lambda read: shown(read.session_lifetime)),
    Column[shpilot.ProjectSettings]("Public access", lambda read: shown(read.public)),
    Column[shpilot.ProjectSettings]("Commit statuses suspended", lambda read: shown(read.commit_statuses_suspended)),
    Column[shpilot.ProjectSettings]("Writable deploy key", lambda read: shown(read.deploy_key_writable)),
    Column[shpilot.ProjectSettings]("Submodules", _submodules),
    Column[shpilot.ProjectSettings]("Storage", lambda read: _storage(read.hosting)),
    Column[shpilot.ProjectSettings]("Workers", lambda read: read.hosting.workers),
    Column[shpilot.ProjectSettings]("Staging branches", lambda read: read.hosting.staging_branches),
    Column[shpilot.ProjectSettings]("Dedicated", lambda read: shown(read.dedicated)),
    Column[shpilot.ProjectSettings]("HTTP timeout", lambda read: _minutes(read.http_timeout_seconds)),
    Column[shpilot.ProjectSettings]("Scheduled actions timeout", lambda read: _minutes(read.cron_timeout_seconds)),
    Column[shpilot.ProjectSettings]("Dev install", lambda read: shown(read.module_install)),
    Column[shpilot.ProjectSettings]("Dev modules", lambda read: shown(read.modules)),
    Column[shpilot.ProjectSettings]("Dev tests", lambda read: shown(read.tests)),
    Column[shpilot.ProjectSettings]("Dev test tags", lambda read: shown(read.test_tags)),
    Column[shpilot.ProjectSettings]("Dev demo data", lambda read: shown(read.demo_data)),
    Column[shpilot.ProjectSettings]("Dev AI agent", lambda read: shown(read.ai_agent)),
    Column[shpilot.ProjectSettings]("IP allow list", lambda read: shown(read.ip_allow_list)),
]
