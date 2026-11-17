# Security

shpilot acts on your Odoo.sh projects with your access, so what it does with that access is a
design constraint rather than a guideline. Much of this page comes from
[odouche](https://github.com/avanserv/odouche), which shpilot is built on; the sections on the
production guard, reusing a browser's login and web sessions are shpilot's own.

## What shpilot holds

- Your **GitHub password** and your **GitHub token** never pass through shpilot. You sign in to
  Odoo.sh with GitHub in a browser, as you do on Odoo.sh itself, or reuse a browser where you
  already did.
- Only the resulting **Odoo.sh session** is kept between runs, in your operating system's keyring.
  It is never written to a plain-text file, a configuration file or a cache.
- In headless use, such as CI, the session is read from the environment and kept in memory only.
- Some of Odoo.sh's answers carry a token or a code: a project's access token, the GitHub token a
  project's admin set for commit statuses, the subscription and enterprise codes, the
  subscription-management link that carries the subscription code, and the credentials, query
  and fragment a submodule URL may hold. shpilot drops each one as the answer arrives, before
  reading anything else, and never stores, logs, shows or returns it. Two are read, and each is
  kept in memory for the one call only: the project's access token, which opens a build's logs
  and mails, and the token of the redirect Odoo.sh answers for a backup's file, which the download
  sends back to fetch the file.

## How you sign in

You choose one of three ways. shpilot never chooses for you: `shpilot auth login` with no option
shows a menu at a terminal, and without a terminal, as in an AI agent's shell, it exits 2 with the
choices, so the agent has to ask you.

Whichever way, the session is kept only after it has answered one request to Odoo.sh.

### Reuse a browser's login (`--from <browser>`)

`shpilot auth browsers` lists the browsers that have data on this machine (Firefox, Chrome,
Chromium, Brave, Edge, Vivaldi, Opera) and, for each, whether one of its profiles holds a
`session_id` cookie of `www.odoo.sh`. To list them, it checks only that such a row exists: no value
is read, nothing is decrypted and no keyring is opened.

`shpilot auth login --from <browser>` then reads, from that one browser:

- the `session_id` cookie of exactly `www.odoo.sh`, the most recently used one across its profiles.
  A cookie set for the whole of `odoo.sh` could come from any of its subdomains, a build's
  included, and is not taken;
- for a Chromium-family browser on Linux, when the cookie is encrypted with a key from the keyring
  (`v11`), that browser's "Safe Storage" secret from the Secret Service; a `v10` cookie uses
  Chromium's fixed key and needs no keyring;
- for a Chromium-family browser on macOS, that browser's "Safe Storage" password from the Keychain,
  through the `security` tool, on its stdout. The Keychain may ask you first.

What it never queries or decrypts: any other cookie, any other site's cookies (GitHub's included),
history, saved passwords or any other browser data. Firefox stores the cookie in clear, so nothing is
decrypted for it.

How it reads:

- The cookie database is opened read-only, in place. Listing never copies it. When a login is
  read and the browser still holds recent changes in its write-ahead log, the whole cookie file and
  its log are copied, into a directory only you can read (under `$XDG_RUNTIME_DIR`, which is in
  memory, where there is one), queried for that one cookie, and deleted at once. The copy holds every
  site's cookies (Firefox's in clear) for that moment; a process killed outright cannot delete it.
- Decryption runs in the shpilot process with the `cryptography` library. The key never reaches a
  command line, a file or a log.
- A locked keyring shows its own unlock dialog. Its password never goes through shpilot.

If Odoo.sh no longer accepts the session that browser holds, nothing is stored and the error says
to log in again in that browser.

On Windows only Firefox's login is reused: Chromium there binds its cookie key to the browser itself,
so nothing outside it can read the cookie, and shpilot does not try. Picking Chrome, Edge, Brave,
Vivaldi or Chromium on Windows opens a fresh sign-in window in that browser instead (below). Firefox's
profiles are found in the AppData folder Windows reports, not through `%APPDATA%`.

### A fresh browser window (`--window`)

shpilot opens a browser window of its own, in which you sign in to Odoo.sh with GitHub. This is
odouche's design.

- The browser is a Chromium-family one already on your machine: Chrome, Chromium, Edge, Brave,
  Vivaldi or Opera, including Brave and Chromium installed as Ubuntu snaps. `SHPILOT_BROWSER`
  names one, by name on the `PATH` or by path. shpilot does not download a browser.
- On Windows the browsers are found in the Program Files and local AppData folders Windows reports,
  never through `PATH`, and you pick which one: `--from edge` opens the window in Edge.
  `SHPILOT_BROWSER` is taken there by absolute path only.
- The window uses a temporary profile that is deleted when the login ends, so you sign in to
  GitHub each time and nothing from that sign-in is kept.
- shpilot talks to the browser over a pipe, not a debugging port that other programs on the machine
  could open (file descriptors 3 and 4 on Linux and macOS; on Windows two pipe handles passed with
  `--remote-debugging-io-pipes`, the only handles the browser inherits), and asks it for one thing: the cookies of `www.odoo.sh`. It does not read what the
  pages show or the cookies of any other site, GitHub included. Some browsers answer before their
  first window exists, so shpilot asks again for up to 15 seconds.
- The profile is deleted when the login is interrupted or the program is terminated, too. On Windows
  the browser and every process it started are ended first (`taskkill /T`, from System32). A program
  that is killed outright cannot delete it. If the profile cannot be deleted, the login fails, the
  session is not kept and the error names the directory to delete.

On Linux with no display, or where no Chromium-family browser is installed, no window can be opened,
and shpilot asks for the cookie to be pasted instead.

### Paste the cookie (`--paste`)

Sign in to Odoo.sh in your own browser and paste the `session_id` cookie of `www.odoo.sh` into a
prompt that does not echo it. No option takes a session: arguments show in the process list and in
the shell history.

## Where the session is stored

shpilot accepts three keyrings and nothing else:

| Environment | Where the session goes |
| --- | --- |
| Linux desktop | Secret Service (GNOME Keyring, KeePassXC and others) |
| macOS | Keychain |
| Windows | Credential Locker |
| WSL2 | Secret Service, once a provider is installed |
| Container, CI | The environment, in memory only |

Any other keyring backend is refused with an error, including the plain-text ones from
`keyrings.alt`. shpilot picks among the three itself, so a keyring configured or installed
elsewhere on the machine cannot become where the session goes.

`shpilot auth logout` ends the session on Odoo.sh and deletes the entry. It is named `session`, under
the service `shpilot`, so you can also find it and delete it by hand.

When none of the three is available, shpilot does not keep the session. It says so and names the
two ways out: install a Secret Service provider, or supply the session through the environment. It
never falls back to a file, and never prints the session for you to export.

A locked keyring shows its own dialog, and its password never goes through shpilot. A dialog left
unanswered ends with an error: after ten seconds, or after the login's timeout during a login.

The environment variable is `SHPILOT_SESSION`. When it is set, the session in the keyring is
neither read nor deleted, and the one from the environment is never stored.

## How long a session lasts

- Odoo.sh decides. If Odoo.sh says a session is no longer valid, shpilot discards it and asks you
  to sign in again. Sessions are never refreshed or extended.
- A client-side maximum age of 30 days applies on top of that, counted from the login and never
  extended by use. A session deleted for its age is not ended on Odoo.sh.
- Logging out ends the stored session on Odoo.sh and deletes it from the keyring. It is deleted
  even when Odoo.sh cannot be reached. A session from the environment is neither ended nor deleted.
- A session reused from a browser is the browser's own session: logging out of shpilot ends it on
  Odoo.sh, and so logs that browser out of Odoo.sh too.

## What never leaves

Session values do not appear in logs, exceptions, object representations or command output.

## The production guard

A change to production waits until a person allows it. The guard covers:

- every command that changes state on a production branch, or on a branch whose stage shpilot
  does not recognise: a rebuild, a backup, its settings, a move;
- every change to a whole project: its settings, its IP allow list, its members;
- a download or a copy of a production backup to this machine;
- `shpilot ssh` on a production build.

Reads are not guarded, and neither is anything on a staging or development branch.

It asks, in this order:

1. A desktop dialog: `/usr/bin/zenity` or `/usr/bin/kdialog` on Linux, `/usr/bin/osascript` on
   macOS, Windows PowerShell from the System32 folder Windows reports on Windows, by those paths only,
   never from `PATH`. **Once**, **Always for \<project\>** (not with
   kdialog, whose exit codes cannot tell a third button from a failure) or **No**. Anything that is
   not a click on Once or Always is No.
2. The terminal the command was started from: `/dev/tty`, never stdin, so input piped into the
   command cannot answer.
3. Nowhere: the command exits 16 and nothing is sent. An AI agent's shell has no terminal, so this
   is what an agent gets when no one is at the desktop.

**Always** is kept per project in `guard.json`: `~/.config/shpilot/` on Linux,
`~/Library/Application Support/shpilot/` on macOS, `shpilot\` in the roaming AppData folder on
Windows. The home directory is taken from the user database, and the Windows folder from Windows
itself (`SHGetKnownFolderPath`), never from `$HOME`, `$XDG_CONFIG_HOME` or `%APPDATA%`, which whoever
starts the command can set. A project name that is not a plain name,
`*` included, is refused before anyone is asked, so one click can never allow every project. The file is written only from an answer to the guard,
with mode 600. `shpilot guard allow` itself needs a person's yes; `shpilot guard ask` only makes the
guard stricter and needs none.

What it stops: the accidental change, and the injected command run as written, the one an agent
runs because a build log, a mail or a web page told it to. That command stops with exit 16 and
nothing sent.

What it does not stop: anything that sets out to get around it. An agent whose shell runs without
asking you (Claude Code's auto or bypass modes, for example) can be led to edit `guard.json` from
the shell, give the command a pseudo-terminal, put another program first on a path, or use the
stored session directly. The guard turns an injected change from one line into a deliberate
workaround; it is not a sandbox. Keep an agent's shell on prompts for anything you have not
allowed, which is what the optional `setup.sh --claude-permissions` rules do. Their deny on editing
the guard's file covers Claude Code's own edit tools, not a shell command.

What it does not cover:

- **Plain `ssh` to production.** Odoo.sh's "Allow my IP" lets this machine's address into every
  build of the project, production included, for an hour, and `shpilot ssh --yes` or `web-session`
  on staging presses it. From then on, plain `ssh`, `scp` or `rsync` with your key reaches the
  production build, and the guard never sees it. The `--claude-permissions` rules ask before any
  `ssh`, `scp`, `rsync` or `sftp` to an `odoo.com` host.
- **Staging data.** A staging build holds a copy of production's data. Backups, browser tests and
  `ssh` on staging are not guarded.
- **A terminal an agent shares.** Where an agent's commands run in your own terminal (some command
  line set-ups), the terminal question lands there, and local programs can type into a terminal on
  some systems. The desktop dialog is the stronger check.

## Web sessions on staging and development

`shpilot web-session login` makes an Odoo web session on a staging or development build as any of
its users, for browser tests.

- It is made on the build, over your `ssh`, by `odoo-bin shell`: the same record a login writes to
  the build's session store. It does not go through the login page, so it needs no password and
  no second factor, and Odoo records no login. The user's own sessions are untouched.
- Production, and any stage shpilot does not recognise, is refused in code before anything is sent
  to the build (exit 9). The guard cannot allow it.
- The session id goes to the build on `ssh`'s stdin and comes back on its stdout, never on a command
  line. It is never printed. It is written to `<dir>/<uid>.session`, mode 600, in a directory of
  mode 700.
- Output from the build is trusted only on lines that carry a random marker made for that run and
  that parse as JSON, so a module on the branch that prints its own lines cannot steer what is
  written where.
- Every session shpilot makes is tagged in the session store with a marker of its run, kept in the
  local file. `logout` deletes the sessions of the runs in `<dir>`, found by that tag, so the ones
  Odoo renamed since (it rotates a session's id) go too. `logout --all` deletes every tagged session
  on the build, leftovers of crashed runs included. A session without the tag is never deleted.
- A logout keeps the local files unless the build confirms every deletion, so it can be run again.

A web session acts as that user, with that user's rights. A staging build holds a copy of
production's data: the people, the invoices, the mail. Whatever a test reads there, screenshots and
`report.json` included, is customer data.

## Build logs and mails

Odoo.sh serves build logs, and the mails a development or a staging build caught, from its worker
hosts, which take a project's access token and not the session.

- The session is sent to `www.odoo.sh` only, never to a worker.
- The token is asked from Odoo.sh for each call and kept in memory for that call. It is never
  stored, logged or shown.
- It is sent over HTTPS to the worker Odoo.sh names, and only when that is a host directly under
  `odoo.com`. Odoo.sh takes it in the address of a log's request, and in the body of a mail's.
- The worker's own address of a mail's HTML and of its pop-out carry the token: shpilot never
  asks for them, builds them or prints them.
- Log content is untrusted. It is whatever a process printed, which can include terminal escape
  sequences and your instance's own secrets. It is returned unchanged and never written to
  shpilot's own log.
- Mail content is untrusted too: the build's code or its data wrote it. An HTML body is turned into
  text. It is never rendered, no link of it is followed and no image is loaded. A mail over 16 MiB
  is not read, nor is a list of mails over 16 MiB. `shpilot` strips a mail of escape sequences,
  control characters and bidirectional controls before printing it, on a terminal or not.
- An agent reading this output reads text a build wrote. Anyone can put text in a production log,
  for instance by typing it into the public login page. The Claude Code skill tells the agent to
  treat it as data, never as instructions, and the production guard is there for when it does not.

## A shell on a build

`shpilot ssh` hands over to your own `ssh`: the `shpilot` process becomes it.

- shpilot reads, generates and uploads no SSH key. `ssh` authenticates with your configuration and
  your agent, against the keys registered on your Odoo.sh profile.
- The user and the host come from Odoo.sh, so each is checked before it is an argument of `ssh`:
  the user is a number and the host is under `odoo.com`, with no label starting with a dash.
- `SHPILOT_SESSION` is removed from the environment `ssh` gets.
- What you give after the options of `shpilot ssh` is given to `ssh` as it is.
- Before that, `shpilot` runs `true` on the build with the same `ssh`, in batch mode and with no
  input, to learn whether it gets in. That try checks no host key and records none, runs no
  command of your configuration and forwards no agent, port or display: it proves only that the
  address gets through. The `ssh` that follows checks the host key as usual.
- `shpilot` reads only the try's stderr: to tell a refusal of your keys, which is not the address,
  and to quote its last line.
- When it does not get in, `shpilot ssh` asks before allowing your address, unless `--yes` is given.
  Odoo.sh takes the address from the request, so shpilot asks no other service for it. Behind a
  proxy set in the environment, the proxy's address is the one allowed.
- On a production build, the production guard asks first.

## A build's panels

`shpilot builds open` prints the URL of a build's monitor, shell or editor, and with `--open` hands it
to your default browser through Python's `webbrowser`.

- The URL holds no token and no session. It keeps only the host of the build's `url`, checked to
  be a bare host under `odoo.com`, or is `www.odoo.sh` with the quoted names of the project and
  the branch: no path, query or user part of an answer reaches it.
- The browser signs in to Odoo.sh on its own, with its own login: shpilot passes it nothing else.
- `SHPILOT_SESSION` is removed from the environment the browser gets.

## What shpilot can change

These calls change something on Odoo.sh. Every other call only reads.

- A rebuild starts a new build of a development or a staging branch.
- A change of a branch's settings sets only the settings named: what a new commit does, on a
  development or a staging branch, and a development branch's new build options. A setting the
  branch's Settings tab does not offer in its stage is refused before anything is sent.
- A change of a project's settings sets only the settings named, for an admin of the project:
  the session lifetime, public access, the defaults of new development branches, the timeouts on
  a dedicated server, and the IP allow list, by entry, never replaced whole.
- A move takes a branch from development to staging, which starts a build on a copy of
  production's data, or from staging to development, which drops its staging builds. Production is
  refused as the branch and as the target before anything is sent, from the stage Odoo.sh gives in
  the same call: the request can carry no other stage than staging or development. A branch made
  production in the page between that read and the move, one request apart, is not caught; only
  Odoo.sh could close that window.
- An addition makes a GitHub user a member of a project with the role given, and a role change
  gives a member another one, for an admin of the project. An admin reaches production, its
  database and shell, and the project's settings. Both read the members in the same call first,
  and refuse before anything is sent an addition of someone already a member, by login or by
  GitHub number, and a change that lowers the last admin who has logged in to Odoo.sh. Odoo.sh
  sends the new member no invitation, and shpilot gives no access to the repository on GitHub.
- A backup is taken of a staging or a production branch's latest build, and Odoo.sh keeps it for
  three days.
- Allowing an IP lets the address of the machine that sends it connect to the builds with `ssh`
  for one hour. The request names a branch, and the rule was seen to open other branches of the
  project too.

For each of them:

- Each request is sent once and never repeated.
- A client opened read-only refuses them before anything is sent.
- Allowing an IP allows only the address the request comes from: shpilot sends no address, so it
  cannot open a build to anyone else. The rule expires by itself, and shpilot never removes one.
- The project's IP allow list takes only the addresses you type into `shpilot projects settings set`.
- The command asks before it sends: its own question, and the production guard on top for
  production and for anything project-wide.

`shpilot web-session` also writes to a build, not to Odoo.sh: it adds and deletes sessions in a
staging or development build's session store, as described above.

## When Odoo.sh changes

Odoo.sh has no public API. shpilot reads the answers its web page uses, and checks their shape.
When Odoo.sh changes one, the command fails with exit 6 and says so; it does not guess, and it does
not return data it could not read with certainty.

## Reporting a vulnerability

Please report vulnerabilities privately, as [SECURITY.md](../SECURITY.md) describes, rather than
in a public issue.
