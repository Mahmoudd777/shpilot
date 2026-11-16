"""The production guard: a change to production waits until a person allows it.

What it guards: every command that changes state on a production branch, every command that changes a whole
project (its settings, its IP allow list, its members), a download or a copy of production data, and `ssh` on a
production build. Reads are never guarded.

How it asks, in order:

1. A desktop dialog (zenity or kdialog on Linux, osascript on macOS), when there is a desktop: Once, Always for
   this project, or No. A program reading the command's output cannot click it, and neither can text it was
   given to read, such as a build log.
2. The terminal the command was started from (`/dev/tty`, never stdin), when there is no desktop.
3. Nowhere: the command refuses, exit 16. An agent's shell has no terminal, so this is what it gets.

"Always" is kept per project in `guard.json`, under the user's real home directory (from the user database, not
`$HOME` or `$XDG_CONFIG_HOME`, which a caller sets). It is written only from an answer to the guard.

What it is not: a defence against a program that already runs as you and means harm. Such a program can edit
`guard.json`, wrap the command in a pseudo-terminal, or call Odoo.sh with the stored session itself. The guard
stops the accidental and the injected change, the one an agent makes because a log or a page told it to.
"""

import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import typer

import shpilot
from shpilot import winpaths as _winpaths
from shpilot.cli._errors import EXIT_GUARDED
from shpilot.cli._output import strip_control


_ALL = "*"
# Only these: a dialog program found on PATH could be any program the caller put there.
_ZENITY, _KDIALOG, _OSASCRIPT = "/usr/bin/zenity", "/usr/bin/kdialog", "/usr/bin/osascript"
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Long enough to read and decide, short enough that a forgotten dialog does not hold a command for good.
_DIALOG_SECONDS = 300


def _home() -> Path:
    """Return the user's home directory as the user database has it, whatever the environment says."""
    import pwd  # noqa: PLC0415

    return Path(pwd.getpwuid(os.getuid()).pw_dir)


def config_path() -> Path | None:
    """Return where the projects allowed without asking are kept, or None when there is no safe place for it.

    The place never comes from the environment: on Linux and macOS the home directory is the user database's, on
    Windows the AppData folder is the one Windows itself reports.
    """
    if sys.platform == "win32":
        app_data = _winpaths.roaming_app_data()
        return app_data / "shpilot" / "guard.json" if app_data is not None else None
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / "shpilot" / "guard.json"
    return _home() / ".config" / "shpilot" / "guard.json"


def allowed() -> set[str]:
    """Return the projects whose production changes run without asking; `*` stands for every project."""
    path = config_path()
    if path is None:
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    names = data.get("allow") if isinstance(data, dict) else None
    return {name for name in names if isinstance(name, str)} if isinstance(names, list) else set()


def _write(names: set[str]) -> None:
    path = config_path()
    if path is None:
        msg = "There is no safe place on this machine to keep the guard's answers."
        raise OSError(msg)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fresh = path.with_suffix(".json.new")
    fresh.write_text(json.dumps({"allow": sorted(names)}, indent=2) + "\n", encoding="utf-8")
    fresh.chmod(0o600)
    fresh.replace(path)


def forget(project: str) -> bool:
    """Ask again for `project` (or for every project, with `*`). Return whether anything changed. Needs no one's yes."""
    names = allowed()
    if project == _ALL:
        changed = bool(names)
        names = set()
    else:
        changed = project in names
        names.discard(project)
    if changed:
        _write(names)
    return changed


def is_production(branch: shpilot.Branch) -> bool:
    """Tell whether a change on `branch` is a change to production. A stage the library does not know counts."""
    return branch.stage in (shpilot.Stage.PRODUCTION, shpilot.Stage.UNKNOWN)


def require(project: str, action: str, *, branch: shpilot.Branch | None = None) -> None:
    """Return when `action` may go ahead; otherwise say why on stderr and exit 16.

    With a `branch`, only a production branch is guarded. Without one, the action is on the whole project and is
    always guarded.
    """
    if branch is not None and not is_production(branch):
        return
    if not _NAME.fullmatch(project):
        typer.echo(strip_control(f"Stopped by the production guard: {project!r} is not a project name."), err=True)
        raise typer.Exit(EXIT_GUARDED)
    names = allowed()
    if project in names or _ALL in names:
        return
    where = f"production of {project}" if branch is not None else f"the whole project {project}"
    answer = _ask(f"{action}\n\nThis changes or reads {where}.", project, always=config_path() is not None)
    if answer == "always":
        _write(allowed() | {project})
        typer.echo(strip_control(f"Production changes on {project} now run without asking. "
                                 f"`shpilot guard ask {project}` undoes it."), err=True)
    if answer in ("once", "always"):
        return
    if answer is None:
        msg = (
            f"Stopped by the production guard. {action} That needs a person to allow it, and there is no desktop "
            f"or terminal here to ask on. Run the same command in your own terminal, or allow {project} for good "
            f"with `shpilot guard allow {project}` there."
        )
    else:
        msg = "Not allowed. Nothing was sent."
    typer.echo(strip_control(msg), err=True)
    raise typer.Exit(EXIT_GUARDED)


def confirm_allow(project: str) -> bool:
    """Ask a person whether every production change on `project` may run without asking from now on."""
    label = "every project" if project == _ALL else project
    answer = _ask(f"Let every production change on {label} run without asking, from now on?", project, always=False)
    return answer == "once"


def _ask(text: str, project: str, *, always: bool = True) -> str | None:
    """Return "once", "always" or "no" as a person answered, or None when no one can be asked."""
    answer = _dialog(text, project, always=always)
    return answer if answer is not None else _terminal(text, project, always=always)


def _has_desktop() -> bool:
    if sys.platform == "darwin":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _applescript(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


_WINDOWS_DIALOG = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$form = New-Object Windows.Forms.Form
$form.Text = 'shpilot: production guard'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.StartPosition = 'CenterScreen'
$form.MinimizeBox = $false
$form.MaximizeBox = $false
$form.AutoSize = $true
$form.AutoSizeMode = 'GrowAndShrink'
$form.Padding = New-Object Windows.Forms.Padding(12)
$panel = New-Object Windows.Forms.FlowLayoutPanel
$panel.FlowDirection = 'TopDown'
$panel.AutoSize = $true
$label = New-Object Windows.Forms.Label
$label.Text = __TEXT__
$label.AutoSize = $true
$label.MaximumSize = New-Object Drawing.Size(460, 0)
$panel.Controls.Add($label)
$row = New-Object Windows.Forms.FlowLayoutPanel
$row.AutoSize = $true
foreach ($choice in __CHOICES__) {
    $button = New-Object Windows.Forms.Button
    $button.Text = $choice[0]
    $button.Tag = $choice[1]
    $button.AutoSize = $true
    $button.Add_Click({ param($sender, $e) $form.Tag = $sender.Tag; $form.Close() })
    $row.Controls.Add($button)
}
$panel.Controls.Add($row)
$form.Controls.Add($panel)
$timer = New-Object Windows.Forms.Timer
$timer.Interval = __MILLISECONDS__
$timer.Add_Tick({ $form.Close() })
$timer.Start()
$form.Tag = 'no'
[void]$form.ShowDialog()
Write-Output $form.Tag
"""


def _powershell_text(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _windows_dialog(text: str, project: str, *, always: bool) -> str | None:
    """Ask in a Windows dialog, through Windows PowerShell at its system path. None when it cannot be shown."""
    system = _winpaths.system_directory()
    if system is None:
        return None
    powershell = system / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        return None
    choices = [("No", "no")] + ([(f"Always for {project}", "always")] if always else []) + [
        ("Once" if always else "Yes", "once")
    ]
    listed = ", ".join(f"@({_powershell_text(label)}, {_powershell_text(value)})" for label, value in choices)
    script = (
        _WINDOWS_DIALOG.replace("__TEXT__", _powershell_text(text))
        .replace("__CHOICES__", f"@({listed})")
        .replace("__MILLISECONDS__", str(_DIALOG_SECONDS * 1000))
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    done = _run([str(powershell), "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded])
    if done is None or done.returncode != 0:
        return None
    picked = done.stdout.strip().splitlines()[-1:] or ["no"]
    return {"once": "once", "always": "always"}.get(picked[0].strip(), "no")


def _dialog(text: str, project: str, *, always: bool) -> str | None:
    """Ask in a desktop dialog. Return None when no dialog could be shown, so the terminal is asked instead."""
    if sys.platform == "win32":
        return _windows_dialog(text, project, always=always)
    if not _has_desktop():
        return None
    yes = "Once" if always else "Yes"
    keep = f"Always for {project}"
    if sys.platform == "darwin" and os.access(_OSASCRIPT, os.X_OK):
        buttons = [_applescript("No")] + ([_applescript(keep)] if always else []) + [_applescript(yes)]
        script = (
            f"display dialog {_applescript(text)} with title {_applescript('shpilot: production guard')} "
            f"buttons {{{', '.join(buttons)}}} default button {_applescript('No')} with icon caution "
            f"giving up after {_DIALOG_SECONDS}"
        )
        done = _run([_OSASCRIPT, "-e", script])
        if done is None or (done.returncode != 0 and "button returned:" not in done.stdout):
            return None
        clicked = done.stdout.split("button returned:", 1)[-1].split(",", 1)[0].strip()
        return {yes: "once", keep: "always"}.get(clicked, "no")
    if os.access(_ZENITY, os.X_OK):
        command = [_ZENITY, "--question", "--title=shpilot: production guard", f"--text={text}",
                   f"--ok-label={yes}", "--cancel-label=No", "--icon=dialog-warning", "--no-markup",
                   f"--timeout={_DIALOG_SECONDS}", "--default-cancel"]
        if always:
            command.append(f"--extra-button={keep}")
        done = _run(command)
        if done is None:
            return None
        if done.returncode == 0:
            return "once"
        if always and done.returncode == 1 and done.stdout.strip() == keep:
            return "always"
        # A dialog that never reached the display: ask on the terminal instead. Anything else is No.
        if done.returncode not in (0, 1, 5) or "display" in done.stderr.lower():
            return None
        return "no"
    if os.access(_KDIALOG, os.X_OK):
        # Two buttons only: kdialog's exit codes cannot tell a third button from a failure, and "Always" is
        # never kept on a guess. `shpilot guard allow` keeps it instead.
        done = _run([_KDIALOG, "--title", "shpilot: production guard", "--warningyesno", text,
                     "--yes-label", yes, "--no-label", "No"])
        if done is None or done.returncode not in (0, 1):
            return None
        return "once" if done.returncode == 0 else "no"
    return None


def _run(command: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run a dialog, or return None when it cannot be started at all."""
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=_DIALOG_SECONDS + 30)  # noqa: S603
    except (OSError, subprocess.TimeoutExpired):
        return None


def _terminal(text: str, project: str, *, always: bool) -> str | None:
    """Ask on the terminal the command was started from (never stdin). None when there is none."""
    windows = sys.platform == "win32"
    try:
        # Windows: the console's own input and output, which a pipe on stdin does not replace.
        reader = open("CONIN$" if windows else "/dev/tty", "r" if windows else "r+", encoding="utf-8")  # noqa: SIM115, PTH123
    except OSError:
        return None
    try:
        writer = open("CONOUT$", "w", encoding="utf-8") if windows else reader  # noqa: SIM115, PTH123
    except OSError:
        reader.close()
        return None
    with reader:
        choices = f"[o]nce, [a]lways for {project}, [N]o" if always else "[y]es, [N]o"
        writer.write(f"\nshpilot: production guard\n{text}\n{choices}: ")
        writer.flush()
        line = reader.readline().strip().lower()
        if writer is not reader:
            writer.close()
    if always:
        return {"o": "once", "once": "once", "a": "always", "always": "always"}.get(line, "no")
    return "once" if line in ("y", "yes") else "no"
