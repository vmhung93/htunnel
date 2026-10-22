import os
import re

CHANNEL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _parse_channel_tokens(raw: str) -> dict[str, str]:
    """Parse "channel=token,channel2=token2" into {channel: token}."""
    channel_tokens: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        channel, sep, token = entry.partition("=")
        channel, token = channel.strip(), token.strip()
        if not sep or not token or not CHANNEL_NAME_PATTERN.fullmatch(channel):
            raise RuntimeError(f"Invalid CHANNEL_TOKENS entry for channel {channel!r}")
        if channel in channel_tokens:
            raise RuntimeError(f"Duplicate channel {channel!r} in CHANNEL_TOKENS")
        if token in channel_tokens.values():
            raise RuntimeError("Each channel in CHANNEL_TOKENS needs its own token")
        channel_tokens[channel] = token
    return channel_tokens


# --- Configuration (environment variables) ---
# Each token can connect to exactly one channel, e.g. "hung=token1,friend=token2"
CHANNEL_TOKENS = _parse_channel_tokens(os.environ.get("CHANNEL_TOKENS", ""))
if not CHANNEL_TOKENS:
    raise RuntimeError("CHANNEL_TOKENS environment variable must be set")

HEARTBEAT_INTERVAL = float(os.environ.get("HEARTBEAT_INTERVAL", "15"))
MAX_BODY_BYTES = int(os.environ.get("MAX_BODY_BYTES", str(5 * 1024 * 1024)))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
PORT = int(os.environ.get("PORT", "10000"))
