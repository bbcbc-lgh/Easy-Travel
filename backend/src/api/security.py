"""Anonymous ownership: one client id per browser, sent as a header."""

import re

from fastapi import Header, HTTPException, status

CLIENT_ID_HEADER = "X-Client-Id"
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def get_owner_id(
    x_client_id: str | None = Header(default=None, alias=CLIENT_ID_HEADER),
) -> str:
    """Return the caller's anonymous owner id, or reject the request."""
    if not x_client_id or not CLIENT_ID_PATTERN.fullmatch(x_client_id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"missing or invalid {CLIENT_ID_HEADER} header (8-64 chars: letters, digits, - or _)",
            headers={"WWW-Authenticate": CLIENT_ID_HEADER},
        )
    return x_client_id
