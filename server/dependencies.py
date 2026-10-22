import secrets

from fastapi import Header, HTTPException

from config import CHANNEL_TOKENS


def require_channel(authorization: str | None = Header(default=None)) -> str:
    """Authenticate the tunnel client and return the channel its token belongs to."""
    provided = (authorization or "").encode()
    matched = None
    # Compare against every token so timing doesn't reveal which one matched
    for channel, token in CHANNEL_TOKENS.items():
        if secrets.compare_digest(provided, f"Bearer {token}".encode()):
            matched = channel
    if matched is None:
        raise HTTPException(status_code=401, detail="Invalid or missing tunnel token")
    return matched
