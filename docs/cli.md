# CLI

`shpilot` is a command-line interface for Odoo.sh, in the spirit of `gcloud`, `aws` and `scw`. It is
based on [odouche](https://github.com/avanserv/odouche) (MIT, by Avanserv): its library and its
command line, renamed, with a production guard, a choice of how to log in and web sessions for
browser tests added.

This page is the guide. `shpilot <command> --help` has every command with its arguments, options
and defaults.

## Install

```bash
uv tool install git+https://github.com/Mahmoudd777/shpilot
shpilot --version
```

With Claude Code, install the plugin instead and run its setup: see the [README](../README.md).

## Sign in

```bash
shpilot auth browsers                 # how you can log in here
shpilot auth login                    # asks which, at a terminal
shpilot auth login --from firefox     # reuse the Odoo.sh login your Firefox holds
shpilot auth login --window           # sign in with GitHub in a fresh window
shpilot auth login --paste            # paste the session_id cookie
```

- `--from` reads one cookie, the `session_id` of www.odoo.sh, from the browser you name, and
  nothing else; `shpilot auth browsers` lists the browsers here and which hold an Odoo.sh login,
  without decrypting anything. `--window` opens a browser with a fresh profile, deleted after the
  login, where you sign in to Odoo.sh with GitHub. `--paste` asks for the cookie in a prompt that
  does not echo it. Without one of them, and without a terminal to ask on, it exits 2 with the
  choices. Either way the session is checked with Odoo.sh, then stored in your operating system's
  keyring, and the account is named.
- [Security](security.md) has what is kept, where and for how long.
- `shpilot auth status` shows where the session comes from, how
  long ago it was stored and when it expires. It exits 3 when there is no usable session, so a
  script can test for one.
- `shpilot auth logout` removes the session from the keyring and
  says whether Odoo.sh ended it.
- No option takes a session: arguments show in the process list and in the shell history. Where
  there is no keyring, as in CI, the session comes from
  [`SHPILOT_SESSION`](#environment-variables).

## Push, watch, read the logs

From a checkout of the repository that the project `acme` builds, on the branch `feature-x`:

```bash
git push
shpilot builds watch
shpilot logs
```

- `shpilot builds watch` waits for the build of the commit you
  pushed, follows it until it finishes and exits with [its result](#exit-codes). Its last line is
  the result and the address of the build's database:

    ```text
    Build 1234 failed: https://acme-feature-x-1234.dev.odoo.com
    ```

- `shpilot logs` prints the end of that build's `install` log, where a
  development build installs the modules and runs their tests. A build that has none, as on a
  staging branch, gives its `odoo` log. `shpilot logs --follow` keeps printing while the build runs.
- As one line: `git push && (shpilot builds watch || shpilot logs)`.
- Anywhere else, name the two: `shpilot builds watch --project acme --branch feature-x`.
- `shpilot builds rebuild --watch`(#rebuilding-a-branch) starts a new build of the branch without a
  commit, and watches it.

## Project and branch

A command that works on a project or a branch takes them from the first of these that gives a
value:

| Order | Project | Branch |
| --- | --- | --- |
| 1 | `--project` | `--branch` |
| 2 | `SHPILOT_PROJECT` | `SHPILOT_BRANCH` |
| 3 | The git checkout's remote, when it is a GitHub repository | The git checkout's current branch |

- The project is given by its name, as `shpilot projects list` shows it.
- The remote is the upstream of the current branch, and `origin` otherwise. A detached HEAD
  gives no branch.
- A repository that several of your projects build is never guessed between: the command exits 2
  and lists them. One that none of them builds exits 4.
- With no source giving a value, or an empty `--project` or `--branch`, the command exits 2.
- `--debug` says on stderr which source was used.

## A project's overview

`shpilot projects show` prints the [project](#project-and-branch)'s overview, one fact per line: its
subscription, Odoo version, region, storage of its quota, workers, staging branches, whether it is
on a dedicated server, its production build, its branches by stage and your access to it.

```bash
shpilot projects show
shpilot --format json projects show --project acme-shop | jq .hosting
```

- Storage, workers and staging branches are on the project's Settings page, which Odoo.sh shows
  to an admin of the project only. Anyone else gets `admins only` in the table, and
  `"hosting": null` in the JSON. The region is shown to every member.
- It asks Odoo.sh what the project's page and its Settings page ask: the project's info, its
  branches and, for an admin, its settings, and the projects for the region. It changes nothing.
- A subscription state `shpilot` does not know is printed as Odoo.sh names it.

## A project's settings

`shpilot projects settings show` prints the [project](#project-and-branch)'s settings, one per line,
as its Settings page has them: the `odoo.com` domain block, the session lifetime, public access,
commit statuses, the deploy key, private submodules, storage, workers, staging branches, dedicated
hosting and its timeouts, the defaults of new development branches, and the IP allow list.

```bash
shpilot projects settings show
shpilot --format json projects settings show --project acme-shop | jq .ip_allow_list
```

- Odoo.sh shows the settings to an admin of the project only. Anyone else exits 5, and the
  settings are not asked for.
- The table gives the timeouts in minutes, as the page does, and a submodule as its URL and the
  fingerprint of its deploy key. The JSON gives the timeouts in seconds and each submodule's
  public deploy key too.
- A submodule URL is shown without its query, its fragment and its credentials, or as `none` when
  it cannot be read safely. Every token and code Odoo.sh sends with the
  settings is dropped unread.
- An allowed entry is shown as written, an address or a network. A setting whose value `shpilot` does
  not know, or an allowed entry that is neither an address nor a network, exits 6.
- It changes nothing on Odoo.sh.

## Changing a project's settings

`shpilot projects settings set` changes the settings of a [project](#project-and-branch) you are an
admin of, and only those given that differ: the others keep their value. It takes `NAME=VALUE` as
`shpilot branches settings set`(#changing-a-branchs-settings) does, named and valued as `shpilot projects
settings show --format json` prints them, and the IP allow list by entry:

```bash
shpilot projects settings set ai_agent=opencode demo_data=no
shpilot projects settings set --add-ip 203.0.113.7 --remove-ip 198.51.100.42
```

- Every value is checked before anything is asked of Odoo.sh: an unknown name or value exits 2.
  `--add-ip` takes an IPv4 address and `--remove-ip` an address or a network as `show` lists it,
  each as many times as needed. `ip_allow_list=` exits 2: the list is never replaced whole.
- A timeout is in seconds, a whole number of minutes within the bounds of the Settings page, and is
  changed on a dedicated server only. Both timeouts are sent, as the page sends them, the other
  with its value as read. The defaults of new development branches follow the rules of
  a branch's new build options. The list holds ten entries at most. Each exits 2 before the question.
- It first says on stderr the project and each setting from its value to the new one, the list
  included. An address already allowed, or an entry not in the list, is said and left out. With
  nothing to change it sends nothing and exits 0.
- A change to the allow list, public access or the session lifetime changes who can reach the
  project: a line says so, and the question asks to change access. SSH from a removed entry then
  needs the one-hour rule `shpilot ssh`(#a-shell-on-a-build) asks for, PostgreSQL on a dedicated
  server is closed to it, and an emptied list is said too.
- `shpilot` cannot tell the address you reach Odoo.sh from without allowing it, so it does not refuse a
  change that removes yours. The list covers SSH, and PostgreSQL on a dedicated server, to
  production and staging: the web page and `shpilot` keep working, and `shpilot ssh` can still allow your
  address for SSH for an hour.
- The list is rebuilt from a read made just before the change, so an edit made elsewhere in
  between is overwritten, as it is by the page.
- It asks and takes `--yes` as [a rebuild](#rebuilding-a-branch) does, and exits 5 for a user who
  is not an admin of the project. The rest is as for a branch: one request, the settings read back
  shown, a setting Odoo.sh moved along said, and exit 10 when Odoo.sh does not confirm the change.
- The project's name, the `odoo.com` domain block, the deploy key, the commit statuses, submodules
  and anything billed are not changed by `set`.

## Checking a project

`shpilot projects check` reads the [project](#project-and-branch)'s overview, as `shpilot projects show`
does, and judges four facts of it. It prints one row per check: its name, its result (`pass`,
`warn`, `fail` or `skip`) and the fact it was judged on. It exits 30 when a check fails, 31 when
none fails and one warns, and 0 otherwise.

```bash
shpilot projects check || case $? in
  30) echo "Something is broken." ;;
  31) echo "Something needs a look." ;;
  *) exit $? ;;
esac
```

| Check | Fails | Warns |
| --- | --- | --- |
| `subscription` | Expired, or in a state `shpilot` does not know, which the project's page calls invalid. | A trial, a non-standard subscription, or a valid one with trial days left. |
| `production` | The last build of a production branch failed. | No production branch, one with no build, or a last build that is running or ended without a result, finished with warnings, or has a result `shpilot` does not know. |
| `storage` | The storage used is at or over the quota. | The storage used is within `--storage-margin` percent of the quota: 10 by default. 0 never warns and 100 warns on any use. |
| `branches` | The last build of any branch, production included, failed. | The last build of a branch has a result `shpilot` does not know. |

- A build dropped for a newer one is judged by the result it had.
- Storage is on the project's Settings page, which Odoo.sh shows to an admin of the project only.
  Anyone else gets `skip` with `admins only`. A quota of 0 is `skip` too, with the storage as
  `shpilot projects show` prints it. A `skip` does not count in the exit code.
- The check names are what a script matches on. `shpilot --format json projects check` gives the same
  rows and exits as the table does. Piped into `jq`, the pipeline exits with `jq`'s code unless
  the script runs `set -o pipefail` or reads `${PIPESTATUS[0]}`.
- It changes nothing on Odoo.sh.

## A project's audit log

`shpilot projects audit` lists the [project](#project-and-branch)'s audit log, newest first: the date
in UTC, who did it, the stage, or `project` for an action on the project, the action and what
Odoo.sh adds about it.

```bash
shpilot projects audit --limit 10
shpilot projects audit --since 2026-10-01
shpilot --format json projects audit --project acme-shop | jq '.[] | select(.kind == "download_database")'
```

- Odoo.sh shows the log to an admin of the project only. Anyone else exits 5, and the log is not
  asked for.
- Odoo.sh sends the whole of the last 30 days in one answer, with no paging. `--limit`, 20 by
  default and 200 at most, and `--since` bound what is printed, not what Odoo.sh sends. Nothing
  older than 30 days can be read, whatever `--since` says.
- `--since` takes a date, `2026-10-01`, or a time, `2026-10-01T09:30:00`, in UTC. `--limit`
  applies first: when it leaves out entries since that date, a line on stderr says so.
- An action `shpilot` does not know is printed as Odoo.sh names it, and one that failed is followed by
  `(failed)`. The author and the details are printed without control characters.
- It changes nothing on Odoo.sh.

## A project's members

`shpilot projects members list` lists the [project](#project-and-branch)'s members: each one's GitHub
login, the name Odoo.sh gives them, their role, and whether they have logged in to Odoo.sh yet.
Admins come first, then testers, then developers, each by login.

```bash
shpilot projects members list
shpilot --format json projects members list | jq '.[] | select(.role == "admin") | .login'
```

- Odoo.sh shows the members to an admin of the project only. Anyone else exits 5, and the
  settings they are part of are not asked for.
- `Logged in` is `no` for a member who was invited and has not logged in to Odoo.sh yet.
- The JSON adds the membership's `id` and the member's GitHub user number, `github_id`. Odoo.sh
  gives no member's email.
- A login and a name are printed on one line without control characters. A role `shpilot` does not
  know exits 6.
- It changes nothing on Odoo.sh.

## Changing a project's members

`shpilot projects members add` adds a GitHub user to the project's members, and `shpilot projects members
role` gives a member another role, `developer`, `tester` or `admin`:

```bash
shpilot projects members add octo-cat --role tester
shpilot projects members role jane-doe developer
```

- An admin reaches production: its database, shell and logs, and the project's settings. A
  tester reaches staging, not production, and a developer development branches only. Only an admin
  of the project changes its members: anyone else exits 5.
- `add` takes `developer` unless `--role` says otherwise, as the page does. Odoo.sh sends the new
  member no invitation, and push access to the repository is given on GitHub, not by `shpilot`.
- `add` takes a login as GitHub takes one for a new account: 1 to 39 letters, digits and single
  inner hyphens. Any other exits 2 before a request; an older login that breaks the rule is added
  in the page. The login is looked up on GitHub through Odoo.sh, as the page's search does, and
  must match exactly: otherwise the command exits 4.
- The lookup needs Odoo.sh's grant on GitHub to cover private repositories. When it does not, the
  command exits 5: search a GitHub user once in the Collaborators item of the project's Settings
  page, which asks GitHub for it, then run it again.
- `role` takes a login as `list` prints it, in any case. One that is not a member exits 4, and a
  member who already has the role exits 0 with nothing sent.
- Both read the members first. Adding someone already a member, by login or by GitHub number under
  a login since renamed, exits 9 with nothing sent, as does lowering the last admin who has logged
  in to Odoo.sh: give another member the admin role first.
- Each first says on stderr the project, the member and the role, from the old one for `role`, and
  what the role reaches. An admin lowering their own role is told they will not be able to change
  it back. It asks, and takes `--yes` in a script, as [a rebuild](#rebuilding-a-branch) does.
- The change is sent once, then the members are read back and the member is shown as `list` shows
  them. When Odoo.sh does not confirm it, or the member does not read back with the role, the
  command exits 10: look with `shpilot projects members list`.
- The production guard asks before either: see [The production guard](#the-production-guard).

## Watching a build

`shpilot builds watch` follows one build until it finishes: the one whose number is given, or the
build of the commit you just pushed.

- When the checkout is of the project's repository and on the branch, however the two were named,
  it waits for a build of the checkout's HEAD to be listed, asking every 3 seconds, and watches
  that one.
- `--commit` waits for another commit of the branch, also when the branch is not the one checked
  out.
- `--no-wait` watches the branch's latest build, whatever its commit, and so does a run with
  no `--commit` on another project or branch than the checkout's, or one where HEAD cannot be
  read.
- The wait for a commit's build lasts two minutes at most, then exits 23: push the commit, or use
  `--no-wait`. `--timeout` covers that wait and the build.
- The changes go to stderr: one line kept up to date when stderr is a terminal, with how long the
  build has run, and one line per change otherwise. The last line, on stdout, is the result and
  the address of the build's database.
- A build that was dropped after it finished exits with the result it had, and is said to have
  been replaced by a newer build. A dropped build has no address.
- Ctrl+C exits 130 and leaves the build running: watching changes nothing on Odoo.sh.

## Rebuilding a branch

`shpilot builds rebuild` starts a new build of the branch, which replaces its latest one. It is one
of the commands that change a project, with
`shpilot branches settings set`(#changing-a-branchs-settings),
`shpilot branches move`(#moving-a-branch-between-stages),
`shpilot projects settings set`(#changing-a-projects-settings),
[`shpilot projects members add` and `role`](#changing-a-projects-members), `shpilot backups create`(#taking-a-backup),
`shpilot backups download`(#downloading-a-backup), and `shpilot ssh`(#a-shell-on-a-build) and
`shpilot backups pull`(#copying-a-backup-over-ssh) when they allow your address. Every other command
that opens a client opens it read-only, and it sends no change.

- Only a development or a staging branch is rebuilt. Any other stage exits 9 before anything is
  asked or sent.
- It first says on stderr what it works on: the project, the branch with its stage, and the
  branch's latest build with its commit. Then it asks on stderr, and anything but `y` or `yes`
  sends nothing and exits 1.
- `--yes` rebuilds without asking. When stdin or stderr is not a terminal it is required: without
  it the command exits 2 and sends nothing. In a script: `shpilot builds rebuild --yes --watch`.
- Once the rebuild is sent, stderr names the new build. It is then shown as `shpilot builds show`
  shows one.
- `--watch` watches the new build as `shpilot builds watch` does, with that command's output and exit
  codes.
- A watch that fails leaves the build as it is: stderr names it, for `shpilot builds watch` to follow.
  Another `rebuild` would start a second build.
- The rebuild is sent once. When Odoo.sh does not confirm it, or the new build is not found, the
  command exits 10: look at `shpilot builds list` before running it again, since a second rebuild
  can start a second build.

## Changing a branch's settings

`shpilot branches settings set` changes the settings it is given, as `NAME=VALUE`, and only those: the
others keep their value. The names and the values are those `shpilot branches settings show --format
json` prints, a yes or no is `yes` or `no`, and `modules` takes names separated by commas:

```bash
shpilot branches settings set --branch feature-x ai_agent=opencode
shpilot branches settings set --branch feature-x project_defaults=no module_install=listed modules=sale,stock
```

- Every value is checked before anything is asked of Odoo.sh: an unknown name or value exits 2.
- What a new commit does, `push_behavior`, is not changed on a production branch, and the new
  build options only on a development branch: either exits 9 before anything is asked or sent.
  While the project's defaults apply, an option is changed with `project_defaults=no` beside it,
  and without it the command exits 2.
- It first says on stderr the project, the branch with its stage, and each setting from its value
  to the new one, or that it already has it. With nothing to change it sends nothing and exits 0.
  Otherwise it asks, and takes `--yes` in a script, as [a rebuild](#rebuilding-a-branch) does.
- The settings that differ are sent once, in one request. The settings read back are then shown as
  `shpilot branches settings show` shows them. Another setting Odoo.sh changed along with them, such as
  the tests once every module is installed, is said on stderr, from its value to the new one, as
  also changed by Odoo.sh.
- When Odoo.sh does not confirm the change, or a setting sent does not read back as sent, the
  command exits 10: look with `shpilot branches settings show`. Sending the same change again does no
  harm.
- The Odoo version and revision, the operating system and the custom domains are not changed by
  `set`.

## Moving a branch between stages

`shpilot branches move --to staging` moves a development branch to staging, and `--to development`
moves a staging branch back:

```bash
shpilot branches move --branch feature-x --to staging
shpilot builds watch --branch feature-x
```

- A move to staging starts a build of the branch on a copy of production's data, with outgoing
  mails caught and scheduled actions turned off, and its next commits build the same way. A move
  to development drops the branch's staging builds, which are not backed up.
- The production branch is not moved, and no branch is moved to production: that is done in the
  Odoo.sh page. `--to production` exits 2. A production branch, or one already in the stage asked,
  exits 9 and sends nothing: before the question when `shpilot branches list` already shows it,
  otherwise once the stage is read again just before the move.
- It first says on stderr the project, the branch with its stage, the move, and what Odoo.sh does
  to the branch. It asks, and takes `--yes` in a script, as [a rebuild](#rebuilding-a-branch) does.
- The move is sent once, then the branch is read back and shown as `shpilot branches list` shows it.
  After a move to staging, stderr names `shpilot builds watch` to follow the new build.
- When Odoo.sh does not confirm the move, or the branch does not read back in the new stage, the
  command exits 10: look with `shpilot branches list`. Running the move again is refused once the
  branch is there.

## Taking a backup

`shpilot backups create` asks Odoo.sh for a manual backup of the branch's latest build, which Odoo.sh
keeps for 3 days. It asks first, and takes `--yes` in a script, as [a rebuild](#rebuilding-a-branch)
does.

- Only a staging or a production branch is backed up. Any other stage exits 9 before anything is
  asked or sent. A backup has only been observed on staging.
- It first says on stderr the project, the branch with its stage, the latest build, and that the
  backup is kept for 3 days. Anything but `y` or `yes` sends nothing and exits 1.
- `--comment` is kept with the backup, as the page's dialog asks.
- Odoo.sh answers nothing about the backup, which it lists about a minute later. Without `--wait`
  the command says so and ends. With `--wait` it asks Odoo.sh every five seconds until the backup
  is listed and finished, then shows it as `shpilot backups list` does. `--timeout` bounds the wait, 600 seconds by
  default; past it the command exits 8, and the backup may still come.
- The request is sent once. When Odoo.sh does not confirm it, the command exits 10: look at
  `shpilot backups list` before running it again, since a second request takes a second backup.

In a script: `shpilot backups create --branch staging --yes --wait`.

## Downloading a backup

`shpilot backups download` has Odoo.sh prepare a backup's file, then writes it to the path `--output`
names. The file is a zip of the database, as `dump.sql`, and of its filestore. It is customer data:
it is created readable by its owner alone (mode `600`), it is never written over an existing file,
and deleting it once you are done is yours to do.

- `BACKUP` is the time that names the backup, in UTC, as `shpilot backups list` shows it, quoted:
  `"2026-10-14 12:48:50"`. Without it, or with `latest`, it is the branch's newest backup that can
  be downloaded. A `remote` backup cannot be: download the `daily` one of the same time.
- `--output` or `--link` is required, so the file never lands somewhere you forget it holds a
  database. Without either, the command exits 2 before asking Odoo.sh anything.
- The database is neutralized, as the page offers it first. `--exact` asks for the real one, and
  `--no-filestore` leaves the filestore out. Only the neutralized one with its filestore has been
  observed.
- Preparing the file changes state on Odoo.sh, so the command asks first and takes `--yes`, as
  [a rebuild](#rebuilding-a-branch) does. It then waits for Odoo.sh to say the file is ready,
  which took 30 seconds for a small database, up to `--timeout` (600 seconds by default; past it,
  exit 8). Odoo.sh keeps a prepared file for 2 hours.
- When Odoo.sh already holds the file of that backup, prepared with the same choices and still
  there, the command takes it: no question, no preparation and no wait. With no terminal,
  `--yes` is still required, so a script does not depend on what Odoo.sh holds.
- A download that fails or is interrupted removes the partial file.
- `--link` prints the page's link to the prepared file on stdout instead. It opens only in a
  browser signed in to Odoo.sh, and grants nothing to anyone else.
- `--new` [takes a backup](#taking-a-backup) of the branch's latest build first, waits for it,
  and downloads it, with one question for both. It never takes a file Odoo.sh holds.
- When Odoo.sh does not confirm the preparation, the command exits 10. Preparing the file again
  does no harm.

In a script: `shpilot backups download --branch staging --new --yes --output staging.zip`.

## Copying a backup over SSH

`shpilot backups pull` copies a backup's SQL, gzipped and without the filestore, from the production
build with your own `rsync`, or `scp` without it. Odoo.sh prepares nothing: the production build
keeps the latest daily backup of production, and the manual backups of every stage, in
`~/backup.daily`. `shpilot` reads no key, and its process becomes `rsync` or `scp`, so the exit code is
then theirs.

- It always connects to the production build, whatever is checked out. `--branch` naming another
  stage exits 2 before anything is tried.
- Without `--manual` it copies the daily backup. `--manual` takes the time of a manual backup, in
  UTC, as `shpilot backups list` shows it, quoted: `"2026-10-14 12:48:50"`.
- `--output` is required, and is never written over. The file is customer data, created readable
  by its owner alone (mode `600`); deleting it is yours to do.
- An address not allowed is handled as `shpilot ssh`(#a-shell-on-a-build) does it, on the
  production branch, with `--yes` to allow without asking.
- Where there is no `rsync`, `scp` or `ssh`, as on native Windows, the command to run by hand is
  shown and `shpilot` exits 14.

In a script: `shpilot backups pull --yes --output daily.sql.gz`.

## Reading a log

A log is untrusted text, and `shpilot logs` writes it to stdout only: nothing of a log goes to
stderr, with `--debug` or without.

- On a terminal the escape sequences and control characters are removed from each line, tabs
  kept, so a line cannot clear the screen or set the window's title. When stdout is a pipe or a
  file the lines are written as they are. `--strip` and `--no-strip` force one or the other.
- A line longer than 64 KiB is cut, and bytes that are not UTF-8 are replaced. A character
  stdout cannot encode is written as its escape, such as `\u2192`.
- Each line is flushed as it is printed. When the pipe it is written to closes, as under
  `shpilot logs | head`, the command ends with nothing on stderr and exits 141.
- `--follow` asks Odoo.sh for new lines every second, until Ctrl+C, which exits 130.
- `--kinds` lists the logs the build has: the kind, what Odoo.sh calls the log, its size and how
  long ago it was last written to. A kind `shpilot` does not know is `unknown`, and `--kind` takes
  its name. A build that waits for a worker has no log yet.
- A log the build does not have exits 4, and the message names the ones it has.

## Reading a build's mails

A development or a staging build sends no mail: Odoo.sh catches each one. `shpilot builds mails`
lists those of the branch's latest build, or of `BUILD_ID`, newest first, and `--mail` shows one
with its body:

```bash
shpilot builds mails --branch staging
shpilot builds mails 88212 --branch staging --limit 5
shpilot builds mails --branch staging --mail 1761213600.M1P1Q1.build
```

- A mail is untrusted text: the build's code or its data wrote it. Its headers and its body are
  printed without escape sequences, control characters and bidirectional controls, tabs kept, on
  a terminal or not.
- An HTML body is printed as text. Nothing in it is rendered, opened or fetched, and there is no
  `--open`.
- With `--format json`, a mail is printed as its model, which JSON escapes.
- A body over 1 MiB, a header over 65536 characters and a mail of more than 1000 MIME parts,
  containers included, are cut, and a mail over 16 MiB is shown without its body or attachments. Either says so on stderr.
- A build that caught nothing says so on stderr and exits 0. A production branch exits 4, and so
  does a mail the build did not catch.

## A shell on a build

`shpilot ssh` opens a shell on the latest build of the [branch](#project-and-branch), with your own
`ssh`: its configuration, its agent and the keys registered on your Odoo.sh account. `shpilot` reads
no key, and its process becomes `ssh`, so the exit code is then `ssh`'s.

- The options of `shpilot` come first. Everything from the first argument on is given to `ssh` after
  the host: a command to run on the build, or options of `ssh`. Put `--` before it when it starts
  with a dash: `shpilot ssh -- -L 8069:localhost:8069`.
- A build with no address exits 4.
- Odoo.sh lets a build be reached only from an allowed address. `shpilot` first runs `true` on the
  build with your `ssh` in batch mode, which asks for nothing. When that does not get in, `shpilot`
  offers to allow the address Odoo.sh sees from your machine for one hour: the "Allow my IP" of
  the branch's page, which was seen to open other branches of the project too. Declining exits 1. `--yes` allows without asking, and is
  needed when stdin or stderr is not a terminal: without it, `shpilot` exits 2.
- Once allowed, `shpilot` tries again every ten seconds for up to ten minutes, then becomes `ssh`.
  Past that it exits 8, with the last line `ssh` printed.
- The try checks no host key, since every build is a new name for the gateway's key: the `ssh`
  `shpilot` becomes asks you about it. When the build refuses your keys (`Permission denied`), the
  address got through: `shpilot` sends nothing and becomes `ssh`.
- Where there is no `ssh` to become, as on native Windows, the command to run by hand is shown
  and `shpilot` exits 14.

## Web sessions for browser tests

```bash
shpilot web-session login --branch staging --out ./sessions admin 7
shpilot web-session logout --branch staging --out ./sessions
shpilot web-session logout --branch staging --out ./sessions --all
```

- `login` makes a web session on the branch's build for each user given, by login or id, with no
  password: the session is written by `odoo-bin shell` over `ssh`, as a login would write it. Each
  goes to `<out>/<uid>.session` (url, db, uid, login, sid), readable by you alone. The session id
  is never printed. A test browser sets it as the `session_id` cookie of the build's URL.
- Staging and development builds only: a production branch, or a stage `shpilot` does not know,
  is refused with exit 9 and nothing is sent.
- `logout` deletes on the build the sessions in `<out>`, then the files, and keeps the files when
  the build does not confirm every deletion. `--all` also deletes every other session `shpilot`
  made on that build: the ones Odoo renamed (it rotates a session's id after a few hours) and the
  ones a crash left behind.
- `--yes` allows this machine's address for `ssh` when it is kept out, as `shpilot ssh --yes` does.
- The login page is skipped, so no second factor is asked and Odoo records no login. A staging
  build holds a copy of production's data: what a test reads there is customer data.

## A build's panels

`shpilot builds open PANEL` prints the URL of the monitor, the shell or the editor of the latest build
of the [branch](#project-and-branch), or of BUILD_ID, as the branch's page links to them. It asks
Odoo.sh only for the branch and its builds, and changes nothing.

```bash
shpilot builds open shell --branch staging
shpilot builds open editor 1234 --open
shpilot builds open monitor --branch main --open
```

- `--open` sends the URL to your default browser instead, and says on stderr which panel of which
  build it sent. The browser signs in to Odoo.sh on its own: `shpilot` hands it the URL and nothing
  else. Where no browser can be started, the URL is printed for you to open and `shpilot` exits 14.
- A build has panels once its status is `done`. One still in progress, waiting for a worker
  included, exits 4.
- The monitor is the branch's, and shows its latest build: it takes no BUILD_ID (exit 2), and only
  a staging or a production branch has one (exit 4).
- The shell and the editor are on the build's own host, which takes the Odoo.sh login of the
  browser too.

## Scripts

### Output

`--format table` (the default) or `--format json`, given before the command. Only the result is
written to stdout, so `shpilot --format json ... | jq` receives nothing else.

```bash
shpilot --format json builds show --project acme --branch feature-x | jq -r .result
```

- JSON is the whole model of the library, and its keys are the model's attribute names. Datetimes are ISO 8601 with an offset.

    | Command | JSON on stdout |
    | --- | --- |
    | `shpilot auth status` | One `SessionInfo`. |
    | `shpilot auth status --check` | One `Identity`, with the `SessionInfo` as its `session`. |
    | `shpilot projects list` | An array of `Project`. |
    | `shpilot projects show` | One `ProjectOverview`. |
    | `shpilot branches list` | An array of `Branch`, in the order of the table. |
    | `shpilot branches history` | An array of `Tracking`, newest first, whatever `--commits` says. |
    | `shpilot projects settings show`, `shpilot projects settings set` | One `ProjectSettings`: after the change, for `set`. |
    | `shpilot branches settings show`, `shpilot branches settings set` | One `BranchSettings`: after the change, for `set`. |
    | `shpilot branches revision` | One `BuildRevision`. Submodule commits are not in it, and a line on stderr says they are not available. |
    | `shpilot backups list` | An array of `Backup`, newest first. |
    | `shpilot backups create --wait` | One `Backup`. Without `--wait`, nothing. |
    | `shpilot builds list` | An array of `Build`. |
    | `shpilot builds show`, `shpilot builds rebuild` | One `Build`. |
    | `shpilot builds open` | The URL, as a JSON string. With `--open`, nothing. |
    | `shpilot builds watch`, `shpilot builds rebuild --watch` | One `Build` per line, for each change, the first being the new build after a rebuild. The result line goes to stderr. |
    | `shpilot logs` | One `LogLine` per line. |
    | `shpilot logs --kinds` | An array of `Log`. |

- These commands print JSON of `shpilot`'s own, which is on one line but for `shpilot projects check`:

    | Command | JSON on stdout |
    | --- | --- |
    | `shpilot projects check` | An array of the checks: `name`, `result` (`pass`, `warn`, `fail` or `skip`) and `fact`. |
    | `shpilot auth login` | `identity`: the `Identity` of the stored session, or `null` when `SHPILOT_SESSION` is set. |
    | `shpilot auth logout` | `source`: where the session came from, or `null` with none. `deleted`: whether it was removed from the keyring. `invalidated`: whether Odoo.sh ended it. `failure`: why Odoo.sh could not be asked, or `null`. |
    | `shpilot --version` | `shpilot` and `shpilot`: the version of each. |

- An empty result is `[]` as JSON, and one line on stderr as a table. Both exit 0.
- A table has no colour and no box drawing when stdout is not a terminal or `NO_COLOR` is set.
  The result of a build is coloured on a terminal, and always written out.
- A table shows times as how long ago they were, except the time that names a backup, which is
  shown in UTC. JSON has the time itself.
- A stage, a status or a result `shpilot` does not know is shown as Odoo.sh names it.
- A table has the control characters removed from every cell, and a tab or a line break made a
  space, so a commit message cannot drive the terminal. JSON has them escaped, in a `LogLine`
  too, so `--strip` has no effect on it. The lines of `shpilot logs`(#reading-a-log) keep them when
  stdout is not a terminal.

### The production guard

A change to production waits until a person allows it. That covers every command that changes state on a
production branch (or a branch in a stage `shpilot` does not know), every change to a whole project (its
settings, its IP allow list, its members), a download or a copy of production data, and `shpilot ssh` on a
production build. Reads are never guarded, and neither is anything on a staging or development branch.

The guard asks, in this order:

1. On the desktop, in a dialog (`/usr/bin/zenity` or `/usr/bin/kdialog` on Linux, `/usr/bin/osascript` on
   macOS, Windows PowerShell from System32 on Windows, never found on `PATH`): **Once**, **Always for the project** (not with kdialog), or **No**.
   Anything but a click on Once or Always is No.
2. On the terminal the command was started from (`/dev/tty`, on Windows the console, never stdin), when there
   is no desktop.
3. Nowhere: the command exits 16 with nothing sent. An AI agent's shell has no terminal, so this is what it
   gets when you are not at the desktop.

**Always** is kept per project in `~/.config/shpilot/guard.json` (macOS: `~/Library/Application
Support/shpilot/`; Windows: `shpilot\guard.json` in the AppData folder Windows reports), never from the
environment. `shpilot guard allow '*'` stops asking for every project. A project name that is not a plain name, `*` included, is refused.
`shpilot guard show` lists the projects that no longer ask, `shpilot guard ask PROJECT` (or `*`) makes them ask
again, and `shpilot guard allow PROJECT` stops asking, which itself needs a person's yes.

The guard stops the accidental change and the injected one run as written: the command an agent runs because a
build log, a mail or a web page told it to. It does not stop what sets out to get around it: an agent whose shell
runs without asking can be led to edit `guard.json`, fake a terminal, or use the stored session directly. Nor
does it see plain `ssh` to a production build once Odoo.sh allowed this machine's IP, which staging SSH does.
[Security](security.md) has the details.

### Exit codes

A command that fails prints one or two lines on stderr, what happened and what to do, and nothing
on stdout. These commands do otherwise:

- `shpilot builds watch`, and `shpilot builds rebuild --watch` like it, exits non-zero for a build that
  did not succeed, with the result line on stdout, or on stderr as JSON. `shpilot builds list` and
  `shpilot builds show` exit 0 whatever the build's result.
- `shpilot logs` can fail after lines went to stdout, at a follow's timeout (8) or when a request
  fails (7).
- `shpilot builds open --open` prints the URL on stdout when no browser can be started, and exits 14.
- `shpilot projects check` prints its checks on stdout when it exits 30 or 31.
- `shpilot ssh`, once it has become `ssh`, exits with what `ssh` exits with: the code of the remote
  command, or 255 for an error of `ssh` itself. The table below is not how to read it.

| Code | Meaning | Returned by |
| --- | --- | --- |
| 0 | Success. `shpilot auth logout` with nothing to log out of is one. | Every command |
| 1 | Unexpected error, which is a bug to report, or a prompt or a question that was declined. | Every command |
| 2 | Usage error: an unknown option, a value an option does not take, options that do not go together, no [project or branch](#project-and-branch), a download with neither `--output` nor `--link`, or to a file that exists or a directory you cannot write to, a rebuild, a move, a backup, a download, a change of settings or members or an IP allow that cannot be confirmed, a login GitHub would not take, a role that is not one, or a setting a branch's Settings tab or a project's Settings page does not let you change with the others as given. | Every command |
| 3 | No session, or an expired one. Run `shpilot auth login`. | Every command that needs the session |
| 4 | The project, branch, build, backup or log is not one the logged-in user can reach. A build that is not among the branch's latest ones is not, and neither is the build of a branch that has none, a backup that cannot be downloaded, a build with no panels yet, the monitor of a development branch, a mail the build did not catch, or the mails of a production branch. A login that is not a member, or that GitHub does not have, is not either. | Every command that takes a project |
| 5 | The session is not allowed to do this, or Odoo.sh's grant on GitHub does not cover the search of a user. | Every command that asks Odoo.sh |
| 6 | Odoo.sh answered in a shape `shpilot` does not read. Please report it. | Every command that asks Odoo.sh |
| 7 | Odoo.sh could not be reached, or answered with a server error. | Every command that asks Odoo.sh |
| 8 | A followed log, a login, a project's audit log, or a backup's or a download's wait reached its timeout, or `ssh` did not get in once the IP was allowed. | `shpilot logs --follow --timeout`, `shpilot auth login`, `shpilot projects audit`, `shpilot backups create --wait`, `shpilot backups download`, `shpilot ssh` |
| 9 | Refused, and nothing was changed: a read-only run, or a branch in a stage `shpilot` does not change, or a setting its Settings tab does not offer in that stage, or a move to the stage a branch is in, or a user added who is already a member, or the last admin lowered. | `shpilot builds rebuild`, `shpilot branches settings set`, `shpilot branches move`, `shpilot projects members add`, `shpilot projects members role`, `shpilot backups create`, `shpilot backups download --new` |
| 10 | A change was sent and Odoo.sh did not confirm it. `shpilot builds list` shows whether a build was started, `shpilot backups list` whether a backup was taken, `shpilot branches settings show` or `shpilot projects settings show` whether the settings were changed, `shpilot branches list` whether a branch was moved, `shpilot projects members list` whether a member was added or given the role; `shpilot ssh`, `shpilot backups download`, either `settings set` and `shpilot projects members role` can be run again. | `shpilot builds rebuild`, `shpilot branches settings set`, `shpilot projects settings set`, `shpilot branches move`, `shpilot projects members add`, `shpilot projects members role`, `shpilot backups create`, `shpilot backups download`, `shpilot ssh` |
| 11 | No usable keyring: none to store the session in, or one that stayed locked. | `shpilot auth login`, `shpilot auth logout`, every command that reads the stored session |
| 12 | The login ended without a session. | `shpilot auth login` |
| 13 | Any other error from the library. | Every command |
| 14 | No `ssh` to hand over to, or native Windows, or no browser could be started. The command to run, or the URL to open, is shown. | `shpilot ssh`, `shpilot builds open --open` |
| 15 | The disk refused the file: full, or no longer writable. Nothing of it is left. | `shpilot backups download` |
| 16 | Stopped by the production guard: a change to production, a project-wide change, a copy of production data or `ssh` on a production build that no one allowed, or that no one could be asked about, because there is no desktop and no terminal. Nothing was sent. See [The production guard](#the-production-guard). | `shpilot builds rebuild`, `shpilot backups create`, `shpilot backups download`, `shpilot backups pull`, `shpilot branches settings set`, `shpilot branches move`, `shpilot projects settings set`, `shpilot projects members add`, `shpilot projects members role`, `shpilot ssh`, `shpilot guard allow` |
| 20 | The build failed. `shpilot logs` is the next step. | `shpilot builds watch`, `shpilot builds rebuild --watch` |
| 21 | The build finished with warnings. | `shpilot builds watch`, `shpilot builds rebuild --watch` |
| 22 | The build ended without a result. It was dropped for a newer build, killed or skipped, or its result is one `shpilot` does not know. | `shpilot builds watch`, `shpilot builds rebuild --watch` |
| 23 | The build had not finished, or had not appeared, at the timeout. | `shpilot builds watch`, `shpilot builds rebuild --watch` |
| 24 to 29 | Reserved for the result of a build. | None yet |
| 30 | A check of the project failed. | `shpilot projects check` |
| 31 | A check of the project warned, and none failed. | `shpilot projects check` |
| 32 to 39 | Reserved for the result of a check. | None yet |
| 130 | Interrupted with Ctrl+C. | Every command |
| 141 | Stdout is a pipe and its reader, such as `head`, closed it. Nothing is written to stderr. | Every command |

`--debug`, or `SHPILOT_DEBUG=1`, adds the traceback on stderr. It shows no local variables, and a
session supplied through `SHPILOT_SESSION` is masked in it.

### Environment variables

| Variable | What it does | Read by |
| --- | --- | --- |
| `SHPILOT_SESSION` | The session to use, as the value of the `session_id` cookie of `www.odoo.sh`. It is kept in memory only, and the keyring is not read. | Every command that needs the session |
| `SHPILOT_PROJECT` | The [project](#project-and-branch), when `--project` is not given. | Every command that takes `--project` |
| `SHPILOT_BRANCH` | The [branch](#project-and-branch), when `--branch` is not given. | Every command that takes `--branch` |
| `SHPILOT_DEBUG` | `SHPILOT_DEBUG=1` is `--debug`. | Every command |
| `NO_COLOR` | Set to a value that is not empty, it leaves tables without colour and box drawing. | Every command that prints a table |
| `DISPLAY` | Set, the production guard asks on the desktop, in a dialog, rather than on the terminal. | Every command the production guard covers |
| `WAYLAND_DISPLAY` | As `DISPLAY`, on Wayland. | Every command the production guard covers |
| `BROWSER` | The browsers to try for `--open`, in Python's `webbrowser` form, before the default one. | `shpilot builds open --open` |
| `DISPLAY`, `WAYLAND_DISPLAY` | On Linux, with neither set, no browser is launched and the cookie is asked for. | `shpilot auth login` |
| `HTTPS_PROXY`, `ALL_PROXY`, `NO_PROXY` | The proxy that requests to Odoo.sh are sent through, and the hosts that are reached without it. The lowercase names are read too. `HTTP_PROXY` has no effect: every request is HTTPS. | Every command that asks Odoo.sh |
| `SSL_CERT_FILE`, `SSL_CERT_DIR` | The certificate authorities trusted for those requests, as a file or a directory, in place of the system's. The file wins over the directory. | Every command that asks Odoo.sh |

- With `SHPILOT_SESSION` set, `shpilot auth login` still stores the session it gets in the keyring,
  and `shpilot auth logout` leaves the variable for you to unset.
- Behind a proxy, the address `shpilot ssh` allows is the proxy's, which Odoo.sh sees. `ssh` does not
  go through the proxy.
- Git, which reads the checkout, and Rich, which draws the tables and the help, read variables of
  their own, such as `GIT_DIR` and `TERM`.

## Shell completion

```bash
shpilot --install-completion
```

- It installs completion for the shell it is run from, such as bash, zsh or fish: a script under
  the home directory, and for bash and zsh a line in `~/.bashrc` or `~/.zshrc`. It takes effect in
  a new shell.
- `shpilot --show-completion` prints the script instead, to install it yourself.
- Commands, options and the values an option lists are completed. Names of projects and branches
  are not: completing asks Odoo.sh nothing and does not open the keyring.
- It needs `shpilot` on the `PATH`, so it does not go with `uvx`.
