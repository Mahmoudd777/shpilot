# Changelog

## 0.1.1

### Changed

- **Log in on Windows with any browser.** `shpilot auth login` on Windows now lists the Chromium-family
  browsers installed (Chrome, Edge, Brave, Vivaldi, Chromium), found in the folders Windows reports.
  Picking one opens a sign-in window in it, with a fresh profile deleted after, as `--window` does on
  Linux and macOS. Their existing logins are still not read: Windows binds them to the browser.
  Firefox's login is reused as before. `--window` works on Windows too.
- The browser is spoken to over two inherited pipe handles (`--remote-debugging-io-pipes`), never a
  network port, and is ended with every process it started (`taskkill /T`).
- `shpilot auth browsers --format json` gives each way an `opens_window` field.
- `shpilot.login()` takes `window=<id>`, an id from the new `shpilot.window_browsers()`.

## 0.1.0 (first release)

The first release of shpilot, based on [odouche](https://github.com/avanserv/odouche) 0.8.1 by
Avanserv. odouche's library and command-line tool are bundled into one package and renamed: the
command is `shpilot`, the environment variables are `SHPILOT_*`, and the session is stored under
the keyring service `shpilot`. It keeps every command of odouche 0.8.1's `osh`, and all
2,639 of odouche's tests pass on the bundle. odouche's MCP server is not included.

### Added

- **Windows, macOS and Linux.** A Windows dialog for the guard (Windows PowerShell from System32), its
  "Always" kept in the AppData folder Windows reports, `setup.sh` under Git Bash, and CI running the
  suite, `setup.sh` and a smoke test on all three systems.

- **Production guard.** Every change to production, every project-wide change (settings, IP allow
  list, members), every download or copy of a production backup, and `shpilot ssh` on a production
  build waits for a person: a desktop dialog (zenity or kdialog on Linux, osascript on macOS) with
  Once, Always for the project, or No; else the terminal the command started from; else exit 16
  with nothing sent. `shpilot guard show|allow|ask` manages the projects that no longer ask.
- **Choice of login.** `shpilot auth browsers` lists the browsers on the machine and which hold an
  Odoo.sh login, without decrypting anything. `shpilot auth login --from <browser>` reuses that
  browser's `www.odoo.sh` session cookie (Firefox, Chrome, Chromium, Brave, Edge, Vivaldi, Opera on
  Linux and macOS; Firefox on Windows). `--window` and `--paste` choose the other two ways. With no option, a menu at a
  terminal; without a terminal, exit 2 with the choices.
- **Login window improvements.** The window waits up to 15 seconds for browsers that answer before
  their first window exists (Brave, Chrome for Testing), finds Brave and Chromium installed as
  Ubuntu snaps, Vivaldi and Opera, and takes `SHPILOT_BROWSER` to choose a browser.
- **`shpilot web-session login|logout [--all]`.** A web session on a staging or development build
  as any user, with no password, made over SSH by `odoo-bin shell`. Production and unknown stages
  are refused (exit 9).
- **Claude Code skill and plugin.** `skills/shpilot` and a plugin marketplace in the repository
  root; `setup.sh` installs the command and checks the machine, and with `--claude-permissions` adds
  permission rules to Claude Code's settings.
- **`browse.sh`.** Headless Playwright click-tests of a staging or development build as any user,
  with screenshots and a `report.json`.

The suite is 2,722 tests, all passing.
