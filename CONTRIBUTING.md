# Contributing

Thank you for helping. Issues and pull requests are welcome.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and git. uv installs the Python version shpilot needs
(3.12 or newer).

```bash
git clone https://github.com/Mahmoudd777/shpilot
cd shpilot
uv sync
uv run shpilot --version
uv run pytest
```

The suite runs against recorded Odoo.sh answers in `tests/core/fixtures/` and a mock transport, so it
needs no Odoo.sh account and no login. Keep it that way: a test that needs the network is a bug.

- `tests/core/`: the library (the client for Odoo.sh, the session store, the browser login, cookie
  reading).
- `tests/cli/`: the `shpilot` command, including the production guard and `web-session`.

To try a change against your own projects, install your checkout as the command:

```bash
uv tool install --force --reinstall .
```

## Rules

- **Never put client data in the repository.** No client or project names, Odoo.sh hosts, build
  URLs, IP addresses, email addresses, logins, session ids or database names, in commits, commit
  messages, issues, test fixtures or screenshots. Use `example.com` addresses, names like `acme`,
  and the documentation IP ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24). A recorded
  Odoo.sh answer used as a fixture is scrubbed before it is committed.
- **Screenshots are customer data until proven otherwise.** A staging build holds a copy of
  production. Take screenshots for docs or issues from a demo database.
- **Pinned dependencies.** `pyproject.toml` pins every dependency to an exact version, because what
  shpilot runs holds a session that reaches production. Raise a pin in its own pull request, with
  the reason.
- **The production guard is not optional.** A new command that changes production, changes a whole
  project, or copies production data calls `_guard.require(...)` before it sends anything, and has
  tests for the refused path (exit 16, nothing sent).
- **Odoo.sh's answers are untrusted.** Check their shape, and fail with a clear error (exit 6)
  rather than guess.
- **Tests with every change.** `uv run pytest` passes before a pull request is opened.
- Keep the docs in step with the code: `docs/cli.md`, `docs/security.md`, `README.md`, and the
  skill's `skills/shpilot/SKILL.md` when the agent's behaviour changes.

## Upstream: odouche

shpilot is [odouche](https://github.com/avanserv/odouche) 0.8.1 bundled and renamed. The mapping:

| odouche | shpilot |
| --- | --- |
| `packages/odouche/src/odouche` | `src/shpilot` |
| `packages/odouche-cli/src/odouche_cli` | `src/shpilot/cli` |
| `packages/odouche/tests` | `tests/core` |
| `packages/odouche-cli/tests` | `tests/cli` |
| the `osh` command, `ODOUCHE_*` variables, keyring service `odouche` | `shpilot`, `SHPILOT_*`, `shpilot` |

The MCP server (`packages/odouche-mcp`) is not bundled.

To take in a new odouche release:

1. Check out the new odouche tag next to this repository, and the previous one (0.8.1 today).
2. Read odouche's changelog and diff the two tags, so you know what changed upstream.
3. Apply that upstream diff to the mapped paths here, with the names renamed as in the table.
   Inside odouche's files, our own edits carry a `# shpilot:` comment; keep them. Files that exist
   only here (`_cookies.py`, `cli/_guard.py`, `cli/guard.py`, `cli/web_session.py`, `skills/`,
   `.claude-plugin/`) are ours and are not touched by a merge.
4. Run `uv run pytest`. Every upstream test must pass, alongside ours.
5. Update `BASED_ON` in `src/shpilot/__init__.py`, `NOTICE.md` and `CHANGELOG.md`, and copy
   odouche's `LICENSE` to `LICENSE.odouche` if it changed.
6. Open the pull request with the odouche version in its title.

Fix a bug in odouche's code upstream first when you can, then merge it here as above.

## Commits and pull requests

Short, imperative subject lines (`Refuse web sessions on an unknown stage`). Explain the why in the
body when the diff does not.

By contributing, you agree that your contribution is licensed under the MIT license of this
repository.
