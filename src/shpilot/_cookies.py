"""Reuse the Odoo.sh login the user already has in their own browser.

Two steps, kept apart on purpose:

- `browsers()` lists the browsers that have data on this machine and says, for each, whether it holds a
  `session_id` cookie of www.odoo.sh. It only checks that such a row exists: no value is read, nothing is
  decrypted, no keyring is opened.
- `session_from(browser_id)` reads that one cookie from that one browser, which the user picked. Firefox keeps it
  in clear. Chromium-family browsers encrypt it: on Linux with a fixed key (v10) or a key in the keyring, "<Browser>
  Safe Storage" (v11); on macOS with a key in the Keychain. The key is derived and used in this process only: it
  never reaches a command line, a file or a log.

No other cookie and no other site is ever read: the queries select the `session_id` of `www.odoo.sh` alone. The
cookie files are opened read-only, in place. Only when a login is read (never when listing) and the browser still
holds recent changes in its write-ahead log is the file copied whole, with its log, into a directory only the
user can read (in memory, under `$XDG_RUNTIME_DIR`, where there is one), queried, and deleted at once.
"""

import contextlib
import glob
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from shpilot import winpaths
from shpilot.secret import Secret


# The one host Odoo.sh sets its session on. A cookie set for the whole of odoo.sh could come from any of its
# subdomains, a build's included, and is not taken.
_HOSTS = ("www.odoo.sh",)
_PLACES = ",".join("?" * len(_HOSTS))


@dataclass(frozen=True, slots=True)
class _Kind:
    id: str
    label: str
    linux: tuple[str, ...]
    macos: tuple[str, ...]
    linux_keyring: str | None = None
    """The `application` attribute of the browser's Safe Storage secret in the Secret Service."""
    macos_keychain: str | None = None
    """The service name of the browser's Safe Storage password in the macOS Keychain."""
    windows: tuple[str, ...] = ()
    """Where its profiles are under the roaming AppData folder, on Windows. Only Firefox: Chromium-family browsers
    bind their cookie key to the browser there, and nothing outside it can read it."""


_FIREFOX = _Kind(
    "firefox",
    "Firefox",
    (
        "~/.mozilla/firefox",
        "~/snap/firefox/common/.mozilla/firefox",
        "~/.config/mozilla/firefox",
        "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
    ),
    ("~/Library/Application Support/Firefox/Profiles",),
    windows=("Mozilla/Firefox/Profiles",),
)
_CHROMIUM = (
    _Kind("chrome", "Google Chrome", ("~/.config/google-chrome",),
          ("~/Library/Application Support/Google/Chrome",), "chrome", "Chrome Safe Storage"),
    _Kind("chromium", "Chromium", ("~/.config/chromium", "~/snap/chromium/common/chromium"),
          ("~/Library/Application Support/Chromium",), "chromium", "Chromium Safe Storage"),
    _Kind("brave", "Brave", ("~/.config/BraveSoftware/Brave-Browser",
                             "~/snap/brave/current/.config/BraveSoftware/Brave-Browser"),
          ("~/Library/Application Support/BraveSoftware/Brave-Browser",), "brave", "Brave Safe Storage"),
    _Kind("edge", "Microsoft Edge", ("~/.config/microsoft-edge",),
          ("~/Library/Application Support/Microsoft Edge",), "microsoft-edge", "Microsoft Edge Safe Storage"),
    _Kind("vivaldi", "Vivaldi", ("~/.config/vivaldi",),
          ("~/Library/Application Support/Vivaldi",), "vivaldi", "Vivaldi Safe Storage"),
    _Kind("opera", "Opera", ("~/.config/opera",),
          ("~/Library/Application Support/com.operasoftware.Opera",), "opera", "Opera Safe Storage"),
)
KINDS = (_FIREFOX, *_CHROMIUM)


@dataclass(frozen=True, slots=True)
class BrowserLogin:
    """A browser with data on this machine, and whether it is logged in to Odoo.sh."""

    id: str
    """What to pass to `login(use=...)`: firefox, chrome, chromium, brave, edge, vivaldi or opera."""

    label: str
    """The browser's name, to show."""

    signed_in: bool
    """Whether one of its profiles holds a `session_id` cookie of www.odoo.sh. Whether Odoo.sh still accepts it
    is known only once it is used."""


def browsers() -> list[BrowserLogin]:
    """Return the browsers with data on this machine, logged in to Odoo.sh first. Nothing is decrypted."""
    found = []
    for kind in KINDS:
        files = _cookie_files(kind)
        if files:
            found.append(BrowserLogin(kind.id, kind.label, any(_has_session(kind, path) for path in files)))
    return sorted(found, key=lambda item: not item.signed_in)


def session_from(browser_id: str) -> Secret | None:
    """Return the newest www.odoo.sh `session_id` the browser `browser_id` holds, or None. Never logged."""
    kind = next((kind for kind in KINDS if kind.id == browser_id), None)
    if kind is None:
        return None
    best: tuple[str, int] | None = None
    for path in _cookie_files(kind):
        found = _firefox_value(path) if kind is _FIREFOX else _chromium_value(kind, path)
        if found is not None and (best is None or found[1] > best[1]):
            best = found
    return Secret(best[0]) if best is not None else None


def label_of(browser_id: str) -> str:
    """Return the name to show for a browser id, or the id itself."""
    return next((kind.label for kind in KINDS if kind.id == browser_id), browser_id)


def _roots(kind: _Kind) -> tuple[str, ...]:
    if sys.platform == "win32":
        # From the folder Windows reports, never %APPDATA%: a caller could point that at a planted cookie.
        app_data = winpaths.roaming_app_data()
        return tuple(str(app_data / folder) for folder in kind.windows) if app_data is not None else ()
    return kind.macos if sys.platform == "darwin" else kind.linux


def _cookie_files(kind: _Kind) -> list[Path]:
    files: list[Path] = []
    for root in _roots(kind):
        base = Path(os.path.expanduser(root))
        if not base.is_dir():
            continue
        if kind is _FIREFOX:
            files += [Path(path) for path in sorted(glob.glob(str(base / "*" / "cookies.sqlite")))]
            continue
        for profile in sorted(base.iterdir()):
            if profile.name != "Default" and not profile.name.startswith("Profile "):
                continue
            for name in ("Network/Cookies", "Cookies"):
                if (profile / name).is_file():
                    files.append(profile / name)
                    break
    return files


def _has_session(kind: _Kind, path: Path) -> bool:
    if kind is _FIREFOX:
        sql = f"SELECT 1 FROM moz_cookies WHERE name = 'session_id' AND host IN ({_PLACES}) AND value != '' LIMIT 1"  # noqa: S608
    else:
        sql = (
            "SELECT 1 FROM cookies WHERE name = 'session_id' "  # noqa: S608
            f"AND host_key IN ({_PLACES}) AND (value != '' OR length(encrypted_value) > 0) LIMIT 1"
        )
    # Listing never copies a file: a login so recent it is still only in the log is missed here, and found on use.
    with _reading(path, recent=False) as connection:
        try:
            return connection is not None and connection.execute(sql, _HOSTS).fetchone() is not None
        except sqlite3.Error:
            return False


def _firefox_value(path: Path) -> tuple[str, int] | None:
    sql = (
        "SELECT value, lastAccessed FROM moz_cookies WHERE name = 'session_id' "  # noqa: S608
        f"AND host IN ({_PLACES}) AND value != '' ORDER BY lastAccessed DESC LIMIT 1"
    )
    with _reading(path) as connection:
        try:
            row = connection.execute(sql, _HOSTS).fetchone() if connection is not None else None
        except sqlite3.Error:
            row = None
    return (row[0], int(row[1])) if row else None


def _chromium_value(kind: _Kind, path: Path) -> tuple[str, int] | None:
    sql = (
        "SELECT host_key, value, encrypted_value, last_access_utc FROM cookies "  # noqa: S608
        f"WHERE name = 'session_id' AND host_key IN ({_PLACES}) ORDER BY last_access_utc DESC"
    )
    with _reading(path) as connection:
        if connection is None:
            return None
        try:
            rows = connection.execute(sql, _HOSTS).fetchall()
            meta = connection.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
        except sqlite3.Error:
            return None
    version = int(meta[0]) if meta and str(meta[0]).isdigit() else 0
    for host, value, encrypted, last in rows:
        plain = value or _decrypt(kind, bytes(encrypted), host, version)
        if plain:
            return plain, int(last)
    return None


@contextlib.contextmanager
def _reading(path: Path, *, recent: bool = True) -> Iterator[sqlite3.Connection | None]:
    """Open a cookie file read-only in place. With `recent`, when its write-ahead log holds data, read a private
    copy of the file and its log instead, so a login made a moment ago is seen.

    Yields None when the file cannot be opened. A query that fails raises `sqlite3.Error` to the caller.
    """
    wal = path.with_name(path.name + "-wal")
    folder: str | None = None
    connection: sqlite3.Connection | None = None
    try:
        if recent and wal.is_file() and wal.stat().st_size > 0:
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            folder = tempfile.mkdtemp(prefix="shpilot-cookies-", dir=runtime if runtime and os.path.isdir(runtime) else None)
            os.chmod(folder, 0o700)
            copy = Path(folder) / "cookies.sqlite"
            shutil.copyfile(path, copy)
            shutil.copyfile(wal, copy.with_name(copy.name + "-wal"))
            connection = sqlite3.connect(str(copy))
        else:
            connection = sqlite3.connect(f"file:{quote(str(path))}?mode=ro&immutable=1", uri=True)
    except (OSError, sqlite3.Error):
        connection = None
    try:
        yield connection
    finally:
        if connection is not None:
            connection.close()
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)


def _decrypt(kind: _Kind, blob: bytes, host: str, version: int) -> str | None:
    prefix = blob[:3]
    if prefix not in (b"v10", b"v11"):
        return None
    key = _key(kind, prefix)
    if key is None:
        return None
    try:
        from cryptography.hazmat.primitives import padding  # noqa: PLC0415
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes  # noqa: PLC0415

        decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        padded = decryptor.update(blob[3:]) + decryptor.finalize()
        unpadder = padding.PKCS7(128).unpadder()
        plain = unpadder.update(padded) + unpadder.finalize()
    except ValueError:
        return None
    # From cookie database version 24, the value starts with the SHA-256 of the host it belongs to.
    if version >= 24 and plain[:32] == hashlib.sha256(host.encode()).digest():
        plain = plain[32:]
    try:
        return plain.decode()
    except UnicodeDecodeError:
        return None


def _key(kind: _Kind, prefix: bytes) -> bytes | None:
    if sys.platform == "darwin":
        password = _macos_password(kind)
        return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1003, 16) if password else None
    if prefix == b"v10":
        # Chromium's fixed key on Linux, for profiles that use no keyring.
        return hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
    password = _linux_password(kind)
    return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", 1, 16) if password else None


def _linux_password(kind: _Kind) -> bytes | None:
    if kind.linux_keyring is None:
        return None
    try:
        import secretstorage  # noqa: PLC0415

        connection = secretstorage.dbus_init()
        try:
            collection = secretstorage.get_default_collection(connection)
            if collection.is_locked():
                # The user picked this browser: the keyring's own dialog asks for its password, not this process.
                collection.unlock()
            item = next(iter(collection.search_items({"application": kind.linux_keyring})), None)
            return item.get_secret() if item is not None else None
        finally:
            connection.close()
    except Exception:  # noqa: BLE001 - no Secret Service, a locked or refused keyring, or no such item
        return None


def _macos_password(kind: _Kind) -> bytes | None:
    if kind.macos_keychain is None or shutil.which("security") is None:
        return None
    # The password comes back on stdout, never on a command line; the Keychain may ask the user first.
    done = subprocess.run(  # noqa: S603
        ["security", "find-generic-password", "-w", "-s", kind.macos_keychain],  # noqa: S607
        capture_output=True, check=False,
    )
    return done.stdout.strip() or None if done.returncode == 0 else None
