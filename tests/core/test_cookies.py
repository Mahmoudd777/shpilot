import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from shpilot import _cookies


SESSION = "0dd0sh-s3ss10n"
OTHER = "n0t-0urs"


def firefox_db(path: Path, rows: list[tuple[str, str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE moz_cookies (name TEXT, value TEXT, host TEXT, lastAccessed INTEGER)")
    connection.executemany("INSERT INTO moz_cookies VALUES (?, ?, ?, ?)", [(*row, n) for n, row in enumerate(rows)])
    connection.commit()
    connection.close()


def v10(value: str, host: str, version: int) -> bytes:
    plain = value.encode()
    if version >= 24:
        plain = hashlib.sha256(host.encode()).digest() + plain
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    key = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)
    encryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
    return b"v10" + encryptor.update(padded) + encryptor.finalize()


def chromium_db(path: Path, rows: list[tuple[str, str, bytes]], version: int = 24) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE meta (key TEXT, value TEXT)")
    connection.execute("INSERT INTO meta VALUES ('version', ?)", (str(version),))
    connection.execute(
        "CREATE TABLE cookies (name TEXT, host_key TEXT, value TEXT, encrypted_value BLOB, last_access_utc INTEGER)"
    )
    connection.executemany(
        "INSERT INTO cookies VALUES (?, ?, '', ?, ?)", [(*row, n) for n, row in enumerate(rows)]
    )
    connection.commit()
    connection.close()


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    roots = {"firefox": tmp_path / "firefox", "brave": tmp_path / "brave"}
    monkeypatch.setattr(_cookies, "_roots", lambda kind: (str(roots[kind.id]),) if kind.id in roots else ())
    monkeypatch.setattr(sys, "platform", "linux")
    return tmp_path


def test_lists_only_browsers_with_data_and_says_which_are_logged_in(home: Path):
    firefox_db(home / "firefox" / "abc.default" / "cookies.sqlite", [("session_id", SESSION, "www.odoo.sh")])
    chromium_db(home / "brave" / "Default" / "Cookies", [("session_id", "example.com", v10(OTHER, "example.com", 24))])

    found = _cookies.browsers()

    assert [(item.id, item.signed_in) for item in found] == [("firefox", True), ("brave", False)]


def test_listing_never_decrypts(home: Path, monkeypatch: pytest.MonkeyPatch):
    chromium_db(home / "brave" / "Default" / "Cookies", [("session_id", "www.odoo.sh", v10(SESSION, "www.odoo.sh", 24))])

    def refused(*_: object) -> None:
        raise AssertionError("decrypted while listing")

    monkeypatch.setattr(_cookies, "_decrypt", refused)
    monkeypatch.setattr(_cookies, "_key", refused)

    assert [(item.id, item.signed_in) for item in _cookies.browsers()] == [("brave", True)]


def test_reads_the_firefox_session_and_no_other_cookie(home: Path):
    firefox_db(
        home / "firefox" / "abc.default" / "cookies.sqlite",
        [("session_id", OTHER, "evil.example"), ("session_id", SESSION, "www.odoo.sh"), ("other", OTHER, "www.odoo.sh")],
    )

    found = _cookies.session_from("firefox")

    assert found is not None
    assert found.expose_secret() == SESSION


@pytest.mark.parametrize("version", [23, 24])
def test_decrypts_a_chromium_v10_session(home: Path, version: int):
    chromium_db(
        home / "brave" / "Profile 1" / "Network" / "Cookies",
        [("session_id", "www.odoo.sh", v10(SESSION, "www.odoo.sh", version))],
        version=version,
    )

    found = _cookies.session_from("brave")

    assert found is not None
    assert found.expose_secret() == SESSION


def test_reads_only_the_browser_asked_for(home: Path, monkeypatch: pytest.MonkeyPatch):
    firefox_db(home / "firefox" / "abc.default" / "cookies.sqlite", [("session_id", SESSION, "www.odoo.sh")])
    chromium_db(home / "brave" / "Default" / "Cookies", [("session_id", "www.odoo.sh", v10(SESSION, "www.odoo.sh", 24))])
    keys: list[str] = []
    real_key = _cookies._key
    monkeypatch.setattr(_cookies, "_key", lambda kind, prefix: keys.append(kind.id) or real_key(kind, prefix))

    _cookies.session_from("firefox")

    assert keys == []


def test_an_unknown_browser_or_one_with_no_login_gives_nothing(home: Path):
    firefox_db(home / "firefox" / "abc.default" / "cookies.sqlite", [("session_id", OTHER, "evil.example")])

    assert _cookies.session_from("firefox") is None
    assert _cookies.session_from("netscape") is None


def test_a_file_with_a_write_ahead_log_is_read_from_a_private_copy_that_is_deleted(
    home: Path, monkeypatch: pytest.MonkeyPatch
):
    db = home / "firefox" / "abc.default" / "cookies.sqlite"
    firefox_db(db, [("session_id", SESSION, "www.odoo.sh")])
    db.with_name("cookies.sqlite-wal").write_bytes(b"\0" * 32)
    runtime = home / "runtime"
    runtime.mkdir()
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))

    found = _cookies.session_from("firefox")

    assert found is not None
    assert list(runtime.iterdir()) == []


def test_a_broken_cookie_file_is_skipped(home: Path):
    path = home / "firefox" / "abc.default" / "cookies.sqlite"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not a database")

    assert _cookies.session_from("firefox") is None
    assert [(item.id, item.signed_in) for item in _cookies.browsers()] == [("firefox", False)]


def test_on_windows_only_firefox_is_offered_from_the_folder_windows_reports(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from shpilot import winpaths

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(winpaths, "roaming_app_data", lambda: tmp_path / "Roaming")
    monkeypatch.setenv("APPDATA", str(tmp_path / "planted"))
    firefox_db(tmp_path / "Roaming" / "Mozilla" / "Firefox" / "Profiles" / "x.default" / "cookies.sqlite",
               [("session_id", SESSION, "www.odoo.sh")])
    firefox_db(tmp_path / "planted" / "Mozilla" / "Firefox" / "Profiles" / "y.default" / "cookies.sqlite",
               [("session_id", OTHER, "www.odoo.sh")])

    found = _cookies.session_from("firefox")

    assert [(item.id, item.signed_in) for item in _cookies.browsers()] == [("firefox", True)]
    assert found is not None and found.expose_secret() == SESSION
