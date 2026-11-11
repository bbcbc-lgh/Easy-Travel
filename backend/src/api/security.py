"""Local ownership: one client id per browser, used only to keep plans apart.

This is **not** authentication. The id is picked by the client and exists so two
browsers on the same machine do not see each other's itineraries. Nothing here
defends a boundary: the server listens on ``127.0.0.1`` and has no accounts.

A missing or malformed id falls back to :data:`LOCAL_OWNER` instead of returning
401, because a single-user instance should not demand ceremony from ``curl``,
``/docs`` or a shell script. Sending a valid id still isolates that browser.
"""

import re

from fastapi import Header

CLIENT_ID_HEADER = "X-Client-Id"
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

#: Owner bucket for requests that carry no usable client id.
LOCAL_OWNER = "local"


def get_owner_id(
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
) -> str:
    """Return the caller's data-isolation bucket, never rejecting the request."""
    if x_client_id and CLIENT_ID_PATTERN.fullmatch(x_client_id):
        return x_client_id
    return LOCAL_OWNER
