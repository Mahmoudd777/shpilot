"""The login window on Windows: the browser is given two pipe handles, and no network port, and is ended with every
process it started. The fake browser runs here; a real one only where `SHPILOT_REAL_BROWSER` is set (Windows CI)."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


if sys.platform != "win32":
    pytest.skip("The Windows launch runs on Windows only.", allow_module_level=True)

from shpilot import LoginError, Secret
from shpilot._upstream import browser
from shpilot._upstream.browser import Capture
from shpilot._upstream.transport import HOST


SESSION = "s3ss10n-v4lu3"
FAKE = Path(__file__).parent / "fake_browser.py"
METHODS = ["Target.getTargets", "Target.attachToTarget", "Network.getCookies", "Browser.close"]


def cookie(value=SESSION):
    return {"name": "session_id", "value": value, "domain": HOST, "path": "/", "httpOnly": True}


def running(pid):
    listed = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"], capture_output=True, text=True, check=False
    ).stdout

    return f'"{pid}"' in listed


class Launched:
    def __init__(self, tmp_path, monkeypatch):
        self.path = str(tmp_path / "chromium.cmd")
        self.profiles = tmp_path / "profiles"
        self.log = tmp_path / "log"
        self._monkeypatch = monkeypatch
        Path(self.path).write_text(f'@"{sys.executable}" "{FAKE}" %*\r\n')
        self.profiles.mkdir()
        monkeypatch.setattr(tempfile, "tempdir", str(self.profiles))
        monkeypatch.setenv("FAKE_BROWSER_LOG", str(self.log))

    def serves(self, *answers, mode=""):
        self._monkeypatch.setenv("FAKE_BROWSER_COOKIES", json.dumps(answers or [[]]))
        self._monkeypatch.setenv("FAKE_BROWSER_MODE", mode)

        return self.path

    @property
    def records(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    @property
    def sent(self):
        return [record for record in self.records if "method" in record]


@pytest.fixture
def launched(tmp_path, monkeypatch):
    launched = Launched(tmp_path, monkeypatch)

    yield launched
    assert list(launched.profiles.iterdir()) == []
    assert not launched.log.exists() or not running(launched.records[0]["pid"])


def test_reads_the_session_over_two_pipe_handles(launched):
    with Capture(launched.serves([cookie()])) as capture:
        assert capture.cookie() == Secret(SESSION)

    argv = launched.records[0]["argv"]
    assert [method["method"] for method in launched.sent] == METHODS
    assert any(arg.startswith("--remote-debugging-io-pipes=") for arg in argv)
    assert "--remote-debugging-pipe" in argv
    assert not any(arg.startswith("--remote-debugging-port") for arg in argv)


def test_a_browser_closed_by_the_user_ends_the_login(launched):
    with pytest.raises(LoginError, match="closed"), Capture(launched.serves(mode="closed")) as capture:
        capture.cookie()


def test_a_browser_that_does_not_close_is_killed(launched, monkeypatch):
    monkeypatch.setattr(browser, "_EXIT_TIMEOUT", 1.0)

    with Capture(launched.serves(mode="hangs")) as capture:
        capture.cookie()


def test_a_browser_that_cannot_be_launched_leaves_nothing(launched, tmp_path):
    with pytest.raises(LoginError, match="could not be launched"), Capture(str(tmp_path / "missing.exe")):
        pass


@pytest.mark.skipif(not os.environ.get("SHPILOT_REAL_BROWSER"), reason="launches a real browser: CI only")
def test_a_real_browser_opens_on_the_login_and_leaves_nothing(tmp_path, monkeypatch):
    installed = browser.window_browsers()
    assert installed, "no Chromium-family browser installed where Windows says"
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    for _, _, path in installed:
        with Capture(path) as capture:
            # Before the sign-in Odoo.sh has set an anonymous session, or none yet.
            assert capture.cookie() is None or isinstance(capture.cookie(), Secret)

        assert list(tmp_path.iterdir()) == []
