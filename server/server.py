import logging

from fastapi import FastAPI

from config import LOG_LEVEL, PORT
from routers import health, tunnel, webhook

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="Custom Webhook Tunnel Relay")

# Global in-memory state, reached from routes via request.app.state.
# This server must run as a single worker/instance.
# clients: channel -> set of connected ClientConnections; webhooks go to all of a channel
app.state.clients = {}

app.include_router(health.router)
app.include_router(tunnel.router)
app.include_router(webhook.router)


if __name__ == "__main__":
    import uvicorn

    # State is in memory, so run exactly one worker.
    # SSE streams never end on their own; the graceful-shutdown timeout closes them on
    # restart/deploy so clients reconnect to the new process instead of the old one.
    uvicorn.run(app, host="0.0.0.0", port=PORT, timeout_graceful_shutdown=5)
