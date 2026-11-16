# Security policy

shpilot holds a session that can reach production Odoo.sh projects, so we take reports seriously.

## Reporting a vulnerability

Please report it privately, through GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/Mahmoudd777/shpilot/security/advisories/new) on
Mahmoudd777/shpilot. Do not open a public issue, pull request or discussion for it.

Include what you can of:

- the version (`shpilot --version`) and your operating system;
- what an attacker needs (a local program, text in a build log, a crafted Odoo.sh answer, and so on)
  and what they get;
- steps to reproduce, or a proof of concept.

Leave out real session ids, client names, hosts, IP addresses and email addresses. Use
`example.com` and the documentation IP ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24).

We will acknowledge the report, keep you informed while we work on it, and credit you in the
advisory unless you prefer otherwise. This is a small team's open-source project: there is no bug
bounty, and no fixed response time.

## Scope

In scope, anything in this repository, in particular:

- the session leaving the keyring: in output, logs, errors, files, a command line or a request to a
  host other than `www.odoo.sh`;
- a way to get past the production guard **without** already running arbitrary code as the user
  (for example, text in a build log or a mail that makes a guarded change go through with no
  person's yes);
- `shpilot auth login --from` reading anything beyond the `www.odoo.sh` `session_id` cookie and the
  browser's own cookie key, or leaving a decrypted copy behind;
- `shpilot web-session` reaching a production build, leaking a session id, or deleting sessions it
  did not make;
- the Claude Code skill, `setup.sh` or `browse.sh` doing something they do not say they do.

Out of scope:

- what a malicious program already running as the user can do. It can edit `guard.json`, use a
  pseudo-terminal or use the stored session directly; [docs/security.md](docs/security.md) states
  this limit;
- vulnerabilities in Odoo.sh or Odoo themselves: report those to Odoo S.A.;
- vulnerabilities in odouche that are not specific to shpilot: please report those to
  [odouche](https://github.com/avanserv/odouche/security) as well, and tell us;
- denial of service against your own machine, and social engineering.

## Supported versions

Only the latest release gets fixes.
