"""The requests about the session's user: who they are, and the logout."""

from shpilot._upstream.reader import Reader
from shpilot._upstream.transport import Transport
from shpilot.models import Identity, SessionInfo


_PROFILE = "/app/user/profile"
_LOGOUT = "/web/session/logout"


def identity(transport: Transport, session: SessionInfo) -> Identity:
    """Return the user the session belongs to."""
    operation = "identity"
    user = Reader(operation, transport.call(operation, _PROFILE, retry=True)).child("result")

    return Identity(
        user_id=user.integer("id"),
        name=user.optional_text("name"),
        username=user.text("username"),
        email=user.optional_text("email"),
        session=session,
    )


def logout(transport: Transport) -> None:
    """End the session on Odoo.sh. Odoo.sh answers the same whether or not the session was valid."""
    transport.leave("logout", _LOGOUT, {"redirect": "/"}, to="/", retry=True)
