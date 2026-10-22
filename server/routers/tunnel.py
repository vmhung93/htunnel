import asyncio
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from config import HEARTBEAT_INTERVAL
from connection import ClientConnection
from dependencies import require_channel
from utils import sse_event

logger = logging.getLogger("htunnel")

# Endpoints used by the local tunnel client
router = APIRouter(dependencies=[Depends(require_channel)])


@router.get("/connect")
async def sse_connect(request: Request, channel: str = Depends(require_channel)):
    """
    SSE Endpoint: Local tunnel clients connect here to listen for incoming webhooks.
    The token decides the channel. Every client of a channel receives its webhooks.
    """
    conn = ClientConnection(channel)
    app_state = request.app.state

    async def event_generator():
        # Register only once streaming starts, so the finally below always unregisters it
        channel_clients = app_state.clients.setdefault(channel, set())
        channel_clients.add(conn)
        logger.info(
            "Tunnel client %s connected to channel %s (%d connected)",
            conn.id,
            channel,
            len(channel_clients),
        )

        try:
            yield sse_event(
                "ping", {"message": "connected", "client_id": conn.id, "channel": channel}
            )

            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(conn.queue.get(), timeout=HEARTBEAT_INTERVAL)
                except TimeoutError:
                    # Keep-alive heartbeat to prevent connection drop from idle proxies
                    yield sse_event("ping", {"message": "heartbeat"})
                    continue

                yield sse_event("webhook", payload)
        finally:
            # Events still queued for this connection are dropped with it, never replayed
            channel_clients.discard(conn)
            if not channel_clients:
                app_state.clients.pop(channel, None)
            logger.info(
                "Tunnel client %s disconnected from channel %s (%d connected)",
                conn.id,
                channel,
                len(channel_clients),
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disables proxy buffering (important for Nginx/Render)
        },
    )
