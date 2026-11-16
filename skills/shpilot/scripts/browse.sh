#!/usr/bin/env bash
# Test an Odoo.sh STAGING or DEVELOPMENT build in a headless browser, logged in as any of its users,
# from a small JS steps file: clicks, forms, lists, RPC, POS, screenshots. Production is refused.
# The session is always logged out afterwards.
#
#   browse.sh <project> <branch> <uid|login> <steps.js> [outdir]
#
#   outdir   default: a new private folder under ${TMPDIR:-/tmp}
#   env      BROWSE_VIEWPORT=1400x900  BROWSE_LOCALE=ar-SA
#
# Needs Node.js and Playwright (npm install -g playwright && npx playwright install chromium).
# Prints a JSON summary; screenshots and report.json land in outdir. Exit 1: the steps threw or the
# page raised JS errors. A staging build holds a copy of production's data: so do the screenshots.
set -uo pipefail
umask 077

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project="${1:-}"; branch="${2:-}"; user="${3:-}"; steps="${4:-}"
[[ -n "$project" && -n "$branch" && -n "$user" && -f "$steps" ]] || { sed -n '2,14p' "$0" >&2; exit 2; }

# Everything that can fail without touching the build is checked first.
command -v shpilot >/dev/null || { echo "shpilot is not installed: run $here/setup.sh" >&2; exit 4; }
shpilot auth status >/dev/null 2>&1 || { echo "not logged in to Odoo.sh: run shpilot auth login" >&2; exit 4; }
command -v node >/dev/null || { echo "Node.js is needed for browser tests" >&2; exit 4; }
node_path="$(npm root -g 2>/dev/null)"
NODE_PATH="$node_path" node -e "require('playwright')" 2>/dev/null \
    || { echo "Playwright is needed: npm install -g playwright && npx playwright install chromium" >&2; exit 4; }

outdir="${5:-$(mktemp -d "${TMPDIR:-/tmp}/shpilot-browse.XXXXXX")}"
mkdir -p "$outdir"
sess="$outdir/.sessions"

cleanup() {
    if shpilot web-session logout --project "$project" --branch "$branch" --out "$sess" >/dev/null 2>&1; then
        rm -rf "$sess"
    else
        echo "logout was not confirmed: the session file is kept in $sess; run" >&2
        echo "  shpilot web-session logout --all --project $project --branch $branch --out $sess" >&2
    fi
}
trap cleanup EXIT

shpilot web-session login --project "$project" --branch "$branch" --out "$sess" --yes -- "$user" || exit 3
file="$(find "$sess" -maxdepth 1 -name '*.session' | head -1)"
[[ -n "$file" ]] || { echo "no session was made for $user" >&2; exit 3; }

NODE_PATH="$node_path" node "$here/browse.js" "$file" "$steps" "$outdir"
rc=$?
echo "outdir: $outdir" >&2
exit $rc
