import base64
import logging
import time
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import CHANNEL_TOKENS
from utils import HOP_BY_HOP_HEADERS, read_limited_body

logger = logging.getLogger("htunnel")

router = APIRouter()

WEBHOOK_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]
# Longest body preview written to the log
LOG_BODY_PREVIEW_BYTES = 2048


@router.api_route("/webhook/{channel}/{path:path}", methods=WEBHOOK_METHODS)
@router.api_route("/webhook/{channel}", methods=WEBHOOK_METHODS)
async def webhook_receiver(request: Request, channel: str, path: str = ""):
    """
    Public webhook receiver endpoint. Catches all HTTP methods and paths, delivers them
    to the clients of the given channel and replies 202 without waiting for them.
    """
    started = time.monotonic()
    request_id = str(uuid.uuid4())
    forward_path = f"/{path}" if path else "/"
    app_state = request.app.state

    def log_result(status_code: int) -> None:
        elapsed_ms = (time.monotonic() - started) * 1000
        logger.info(
            "%s [%s] %s %s -> %d (%.0fms)",
            request_id,
            channel,
            request.method,
            forward_path,
            status_code,
            elapsed_ms,
        )

    # Behind a proxy (e.g. Render) the caller's address is the first X-Forwarded-For entry
    forwarded_for = request.headers.get("x-forwarded-for", "")
    caller_ip = forwarded_for.split(",")[0].strip() or (
        request.client.host if request.client else "-"
    )
    query = f"?{request.url.query}" if request.url.query else ""
    logger.info(
        "%s [%s] %s %s%s from %s (%s)",
        request_id,
        channel,
        request.method,
        forward_path,
        query,
        caller_ip,
        request.headers.get("user-agent", "-"),
    )

    if channel not in CHANNEL_TOKENS:
        log_result(404)
        return JSONResponse({"error": "Unknown channel"}, status_code=404)

    # Fail fast instead of queuing an event nobody will receive
    if not app_state.clients.get(channel):
        log_result(503)
        return JSONResponse({"error": "No tunnel client connected"}, status_code=503)

    raw_body = await read_limited_body(request)
    logger.info(
        "%s [%s] headers=%s body=%s",
        request_id,
        channel,
        dict(request.headers),
        raw_body[:LOG_BODY_PREVIEW_BYTES].decode("utf-8", errors="replace"),
    )

    payload = {
        "request_id": request_id,
        "method": request.method,
        "path": forward_path,
        # Header and query lists preserve repeated keys
        "headers": [
            [k, v]
            for k, v in request.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS
        ],
        "query_string": request.url.query,
        # Base64 keeps the body byte-exact, which webhook signature checks depend on
        "body_b64": base64.b64encode(raw_body).decode("ascii"),
    }

    # Clients may have disconnected while the body was being read
    clients = list(app_state.clients.get(channel, ()))
    if not clients:
        log_result(503)
        return JSONResponse({"error": "No tunnel client connected"}, status_code=503)

    # Fire and forget: hand the event to every client of the channel and answer at once
    for client in clients:
        client.queue.put_nowait(payload)

    log_result(202)
    return JSONResponse({"status": "accepted", "request_id": request_id}, status_code=202)
