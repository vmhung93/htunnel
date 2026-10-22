import asyncio
import uuid


class ClientConnection:
    """One connected SSE tunnel client with its own event queue."""

    def __init__(self, channel: str) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.channel = channel
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
