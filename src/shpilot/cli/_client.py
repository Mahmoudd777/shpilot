"""The library client, built in one place and only when a command needs it."""

import os

import shpilot


def open_client(*, writes: bool = False) -> shpilot.Client:
    """Open the client on the session in use: read-only, unless the command is one that `writes`."""
    return shpilot.Client(read_only=not writes)


def forget_session_env() -> None:
    """Remove the session from this process's environment, before it starts a program that inherits it."""
    # The session is not `ssh`'s or a browser's to inherit, nor that of a program either runs.
    # `webbrowser` takes no environment of its own, so this process's is the one to change.
    if shpilot.SESSION_ENV in os.environ:
        del os.environ[shpilot.SESSION_ENV]
