#!/usr/bin/env bash
# Install shpilot from this checkout and check what it needs. Safe to run again; it deletes nothing.
#
#   setup.sh                        install or update the `shpilot` command, then check the machine
#   setup.sh --claude-permissions   also add Claude Code permission rules: reads allowed; SSH (shpilot's
#                                   and raw ssh/rsync to Odoo.sh) and every change asked; Claude's edit
#                                   tools kept off the guard's file. A backup of settings.json is kept.
#
# Linux, macOS, WSL, and Windows in Git Bash (the shell Claude Code uses there).
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"
claude_permissions=0
for arg in "$@"; do
    case "$arg" in
        --claude-permissions) claude_permissions=1 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

user_path="$PATH"
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) os=windows ;;
    Darwin) os=macos ;;
    *) os=linux ;;
esac
[[ -f "$root/pyproject.toml" && -d "$root/src/shpilot" ]] || { fail "not a shpilot checkout: $root"; exit 1; }

step "1. uv (installs shpilot and the Python it needs)"
if ! command -v uv >/dev/null 2>&1 && [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi
if command -v uv >/dev/null 2>&1; then
    ok "uv $(uv --version | awk '{print $2}')"
else
    warn "uv is not installed. Its official installer is:"
    if [ "$os" = windows ]; then
        install='powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"'
    else
        install='curl -LsSf https://astral.sh/uv/install.sh | sh'
    fi
    echo "     $install"
    if [ -t 0 ] && [ -t 1 ]; then
        read -r -p "     Run it now? [y/N] " yes
        [[ "$yes" =~ ^[Yy] ]] || { echo "     Install uv, then run this again."; exit 3; }
        if [ "$os" = windows ]; then
            powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex" || { fail "the uv installer failed"; exit 3; }
        else
            curl -LsSf https://astral.sh/uv/install.sh | sh || { fail "the uv installer failed"; exit 3; }
        fi
        export PATH="$HOME/.local/bin:$PATH"
    else
        echo "     Run it in a terminal, then run this again."; exit 3
    fi
fi

step "2. shpilot"
if uv tool install --force --reinstall --quiet "$root"; then
    tool_bin="$(uv tool dir --bin 2>/dev/null || echo "$HOME/.local/bin")"
    [ "$os" = windows ] && command -v cygpath >/dev/null 2>&1 && tool_bin="$(cygpath -u "$tool_bin")"
    ok "$("$tool_bin/shpilot" --version) from $root"
    if ! PATH="$user_path" command -v shpilot >/dev/null 2>&1; then
        warn "$tool_bin is not on your PATH: run  uv tool update-shell  and open a new terminal"
    fi
    export PATH="$tool_bin:$PATH"
else
    fail "uv tool install failed"; exit 1
fi

step "3. How you can log in"
shpilot auth browsers | sed 's/^/     /'
echo "     Log in with:  shpilot auth login   (it asks which; an agent passes --from <browser> after asking you)"

step "4. The production guard"
case "$os" in
    windows) ok "asks in a Windows dialog (Windows PowerShell)" ;;
    macos) ok "asks in a macOS dialog (osascript)" ;;
    linux)
        if [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
            if command -v zenity >/dev/null 2>&1 || command -v kdialog >/dev/null 2>&1; then
                ok "asks in a desktop dialog ($(command -v zenity >/dev/null 2>&1 && echo zenity || echo kdialog))"
            else
                warn "no zenity or kdialog: the guard asks on the terminal instead (Ubuntu: sudo apt install zenity)"
            fi
        else
            ok "no desktop here: the guard asks on the terminal"
        fi ;;
esac

step "5. Keyring (where the Odoo.sh session is kept)"
case "$os" in
    windows) ok "Windows Credential Locker" ;;
    macos) ok "macOS Keychain" ;;
    linux)
        if busctl --user list 2>/dev/null | grep -q org.freedesktop.secrets; then
            ok "Secret Service is running"
        else
            warn "no Secret Service: install one (Ubuntu: sudo apt install gnome-keyring), or set SHPILOT_SESSION for a headless run"
        fi ;;
esac

step "6. SSH key (for shpilot ssh)"
command -v ssh >/dev/null 2>&1 && ok "ssh client present" || fail "no ssh client: install OpenSSH (Windows: Settings > Optional features > OpenSSH Client)"
pub=""
for key in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_ecdsa.pub" "$HOME/.ssh/id_rsa.pub"; do
    [ -f "$key" ] && { pub="$key"; break; }
done
if [ -n "$pub" ]; then
    ok "key: $pub"
    echo "     Odoo.sh does not use your GitHub keys by itself. Add this one on www.odoo.sh:"
    echo "     your name (top right) > Profile > SSH Keys > Add a key manually  (or Import from GitHub)"
else
    warn "no SSH key yet:  ssh-keygen -t ed25519 -C you@example.com  then add the .pub on www.odoo.sh"
fi

step "7. Claude Code"
if [ "$claude_permissions" = 1 ]; then
    # uv's own Python: Windows has no python3 on PATH by default.
    uv run --no-project --quiet python - <<'EOF'
import json, os, shutil, tempfile, time
# A settings file that is a link is changed where it points, and stays a link.
path = os.path.realpath(os.path.expanduser("~/.claude/settings.json"))
data = {}
if os.path.exists(path):
    with open(path, encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict) or not isinstance(data.get("permissions", {}), dict):
        raise SystemExit(f"  {path} is not a settings object: nothing changed")
    backup = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, backup)
    print(f"  backup: {backup}")
reads = ["--version", "auth status", "auth browsers", "projects list", "projects check", "branches list",
         "branches history", "branches revision", "builds list", "builds show", "builds watch", "builds mails",
         "logs", "backups list", "guard show"]
allow = [f"Bash(shpilot {cmd} *)" for cmd in reads] + [f"Bash(shpilot --format json {cmd} *)" for cmd in reads]
ask = ["Bash(shpilot ssh *)", "Bash(shpilot web-session *)", "Bash(shpilot auth login *)", "Bash(shpilot auth logout *)",
       "Bash(shpilot *rebuild*)", "Bash(shpilot *backups create*)", "Bash(shpilot *backups download*)",
       "Bash(shpilot *backups pull*)", "Bash(shpilot *settings set*)", "Bash(shpilot *members*)",
       "Bash(shpilot *branches move*)", "Bash(shpilot *guard allow*)", "Bash(shpilot *guard ask*)",
       # Once Odoo.sh allows this machine's address (staging does), plain ssh reaches every build of the
       # project, production included, and the guard never sees it.
       "Bash(ssh *odoo.com*)", "Bash(scp *odoo.com*)", "Bash(rsync *odoo.com*)", "Bash(sftp *odoo.com*)"]
deny = ["Edit(~/.config/shpilot/**)", "Edit(~/Library/Application Support/shpilot/**)",
        "Edit(~/AppData/Roaming/shpilot/**)"]
perms = data.setdefault("permissions", {})
added = 0
for key, rules in (("allow", allow), ("ask", ask), ("deny", deny)):
    have = perms.setdefault(key, [])
    for rule in rules:
        if rule not in have:
            have.append(rule); added += 1
os.makedirs(os.path.dirname(path), exist_ok=True)
fd, fresh = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".settings-", suffix=".json")
with os.fdopen(fd, "w", encoding="utf-8") as file:
    json.dump(data, file, indent=2); file.write("\n")
os.replace(fresh, path)
print(f"  \033[32m✓\033[0m ~/.claude/settings.json: {added} rule(s) added: reads allowed; shpilot ssh, raw ssh/rsync to Odoo.sh and every change asked; Claude's edit tools kept off the guard's file")
EOF
else
    echo "     (optional) run again with --claude-permissions to add the permission rules described in README.md"
fi

step "8. Session"
if shpilot auth status >/dev/null 2>&1; then
    shpilot auth status | sed 's/^/  /'
else
    warn "not logged in yet: shpilot auth login"
fi
echo
