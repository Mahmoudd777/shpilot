import ast
from importlib.metadata import version
from pathlib import Path

import pytest

import shpilot


CLI_SOURCES = Path(__file__).parents[2] / "src" / "shpilot" / "cli"


def private_imports(source):
    """Return the modules and names under `shpilot` that a source imports and that are private."""
    found = []

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names = [f"{node.module}.{alias.name}" for alias in node.names]
        else:
            continue

        for name in names:
            root, *parts = name.split(".")

            # The command-line frontend lives in `shpilot.cli`: its own private modules are its business.
            if parts[:1] == ["cli"]:
                continue
            if root == "shpilot" and any(part.startswith("_") and not part.startswith("__") for part in parts):
                found.append(name)

    return found


def test_version_matches_distribution_metadata():
    assert shpilot.__version__ == version("shpilot")


@pytest.mark.parametrize(
    ("source", "found"),
    [
        ("import shpilot\nfrom shpilot import Client, __version__\nfrom shpilot.errors import OdoucheError", []),
        ("import shpilot._session", ["shpilot._session"]),
        ("from shpilot import _client", ["shpilot._client"]),
        ("from shpilot._upstream.transport import Transport", ["shpilot._upstream.transport.Transport"]),
        ("import shpilot.cli._private\nfrom . import _private", []),
    ],
)
def test_finds_an_import_of_a_private_module(source, found):
    assert private_imports(source) == found


def test_the_cli_imports_only_the_public_api():
    sources = sorted(CLI_SOURCES.rglob("*.py"))

    assert sources
    assert [name for path in sources for name in private_imports(path.read_text(encoding="utf-8"))] == []
