# Notice

shpilot includes code from **odouche** 0.8.1, <https://github.com/avanserv/odouche>,
Copyright (c) 2026 Avanserv, under the MIT license. Its license text is in
[LICENSE.odouche](LICENSE.odouche) and applies to that code.

## What came from odouche

odouche worked out how the Odoo.sh web page talks to Odoo.sh, which has no public API, and built a
careful, well-tested client on it. In shpilot, renamed from `odouche` and `odouche_cli`:

- `src/shpilot/`: odouche's library: the client, the requests and answer shapes in
  `src/shpilot/_upstream/`, the session store, the browser login and the logout.
- `src/shpilot/cli/`: odouche's `osh` command-line tool.
- `tests/core/` and `tests/cli/`: odouche's tests and recorded fixtures, which all pass on this
  bundle.
- `docs/cli.md` and parts of `docs/security.md`: odouche's documentation, adapted.

## What is shpilot's own

Under this repository's [LICENSE](LICENSE) (MIT, Copyright (c) 2026 Mahmoud Shrief, Global Solutions):

- `src/shpilot/_cookies.py`: reusing a browser's Odoo.sh login.
- `src/shpilot/cli/_guard.py` and `src/shpilot/cli/guard.py`: the production guard.
- `src/shpilot/cli/web_session.py`: web sessions on staging and development builds.
- Changes to odouche's files for the above: the login choice in `_login.py` and `cli/auth.py`,
  the guard calls in the commands, and the browser finding in `_upstream/browser.py` (marked
  `# shpilot:`).
- `skills/shpilot/` (the Claude Code skill, `setup.sh`, `browse.sh`, `browse.js`) and
  `.claude-plugin/`.
- The tests for these.

Not affiliated with Odoo S.A. "Odoo" and "Odoo.sh" are trademarks of Odoo S.A.
