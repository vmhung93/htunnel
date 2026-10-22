import argparse
import asyncio
import base64
import json
import logging
import os
import random
import sys
import time

import httpx
from httpx_sse import SSEError, aconnect_sse

logger = logging.getLogger("htunnel-client")

# The server sends a ping every 15s; treat a much longer silence as a dead connection
SSE_READ_TIMEOUT = 60.0
BACKOFF_INITIAL = 1.0
BACKOFF_MAX = 30.0

# ANSI colors only when logging to a terminal; respect https://no-color.org
USE_COLOR = sys.stderr.isatty() and "NO_COLOR" not in os.environ
GREEN, CYAN, YELLOW, RED, BOLD = "32", "36", "33", "31", "1"


def color(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def status_color(status: int) -> str:
    if status >= 500:
        return RED
    if status >= 400:
        return YELLOW
    if status >= 300:
        return CYAN
    return GREEN


class AuthError(Exception):
    """The server rejected the token; retrying will not help."""


class TunnelClient:
    def __init__(
        self, remote_url: str, token: str, local_url: str, local_timeout: float, concurrency: int
    ) -> None:
        self.remote_url = remote_url.rstrip("/")
        self.token = token
        self.local_url = local_url.rstrip("/")
        self.local_timeout = local_timeout
        self.semaphore = asyncio.Semaphore(concurrency)
        self.tasks: set[asyncio.Task] = set()

    async def run(self) -> None:
        # Separate clients so cookies and settings never leak between the relay and the local app.
        # The relay client is only used for the SSE stream.
        remote = httpx.AsyncClient(
            base_url=self.remote_url,
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=httpx.Timeout(10.0, read=SSE_READ_TIMEOUT),
        )
        local = httpx.AsyncClient(timeout=self.local_timeout, follow_redirects=False)
        backoff = BACKOFF_INITIAL
        try:
            while True:
                connected_at = None
                try:
                    logger.info("Connecting to %s ...", self.remote_url)
                    async for _ in self.listen(remote, local):
                        # Yields once the server confirms the connection
                        connected_at = time.monotonic()
                        backoff = BACKOFF_INITIAL
                    logger.warning("Server closed the tunnel connection")
                except AuthError:
                    raise
                except (httpx.HTTPError, SSEError) as err:
                    logger.warning("Connection lost: %s", err or type(err).__name__)

                # A connection that lasted a while counts as healthy, so start backoff over
                if connected_at and time.monotonic() - connected_at > BACKOFF_MAX:
                    backoff = BACKOFF_INITIAL
                delay = backoff * random.uniform(0.5, 1.0)
                logger.info("Reconnecting in %.1fs", delay)
                await asyncio.sleep(delay)
                backoff = min(backoff * 2, BACKOFF_MAX)
        finally:
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            await remote.aclose()
            await local.aclose()

    async def listen(self, remote: httpx.AsyncClient, local: httpx.AsyncClient):
        async with aconnect_sse(remote, "GET", "/connect") as event_source:
            if event_source.response.status_code == 401:
                raise AuthError("Server rejected the token (401). Check HTUNNEL_TOKEN.")
            event_source.response.raise_for_status()

            async for sse in event_source.aiter_sse():
                if sse.event == "ping":
                    data = json.loads(sse.data)
                    if data.get("message") == "connected":
                        channel = data.get("channel")
                        logger.info(
                            "Tunnel connected (channel %s, client %s). Webhook URL: %s/webhook/%s/",
                            channel, data.get("client_id"), self.remote_url, channel,
                        )
                        yield
                elif sse.event == "webhook":
                    # Handle concurrently so a slow local request never blocks the stream
                    webhook = json.loads(sse.data)
                    task = asyncio.create_task(self.handle_webhook(local, webhook))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)

    async def handle_webhook(self, local: httpx.AsyncClient, webhook: dict) -> None:
        """Rebuild the webhook request and send it to the local app (the server already replied)."""
        request_id = webhook["request_id"]
        method = webhook["method"]
        path = webhook["path"]
        query_string = webhook.get("query_string", "")
        target_url = f"{self.local_url}{path}" + (f"?{query_string}" if query_string else "")
        started = time.monotonic()

        async with self.semaphore:
            try:
                response = await local.request(
                    method,
                    target_url,
                    headers=[(k, v) for k, v in webhook["headers"]],
                    content=base64.b64decode(webhook["body_b64"]),
                )
            except httpx.TimeoutException:
                logger.error(
                    "%s %s -> %s [%s]",
                    color(method, BOLD), path,
                    color(f"local app timed out after {self.local_timeout:.0f}s", RED),
                    request_id[:8],
                )
                return
            except httpx.RequestError as exc:
                logger.error(
                    "%s %s -> %s: %s [%s]",
                    color(method, BOLD), path,
                    color(f"cannot reach local app at {self.local_url}", RED),
                    repr(exc), request_id[:8],
                )
                return

        elapsed_ms = (time.monotonic() - started) * 1000
        log = logger.warning if response.is_error else logger.info
        log(
            "%s %s -> %s (%.0fms) [%s]",
            color(method, BOLD), path,
            color(str(response.status_code), status_color(response.status_code)),
            elapsed_ms, request_id[:8],
        )


def parse_local(value: str) -> str:
    """Accept a port ("8080") or a full URL ("http://127.0.0.1:3000")."""
    return f"http://localhost:{value}" if value.isdigit() else value


def main() -> None:
    parser = argparse.ArgumentParser(description="htunnel client: forward webhooks to a local app")
    parser.add_argument(
        "--remote",
        default=os.environ.get("HTUNNEL_REMOTE"),
        help="Relay server base URL, e.g. https://my-relay.onrender.com (env: HTUNNEL_REMOTE)",
    )
    parser.add_argument(
        "--local",
        default=os.environ.get("HTUNNEL_LOCAL", "8080"),
        help="Local app port or URL, e.g. 8080 or http://127.0.0.1:3000 (env: HTUNNEL_LOCAL)",
    )
    parser.add_argument(
        "--local-timeout",
        type=float,
        default=float(os.environ.get("HTUNNEL_LOCAL_TIMEOUT", "30")),
        help="Seconds to wait for the local app (env: HTUNNEL_LOCAL_TIMEOUT)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("HTUNNEL_CONCURRENCY", "10")),
        help="Max webhooks forwarded to the local app at once",
    )
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    # httpx logs every request at INFO; keep the output to tunnel events
    logging.getLogger("httpx").setLevel(logging.WARNING)

    # The token comes from the environment only, so it never lands in shell history
    token = os.environ.get("HTUNNEL_TOKEN")
    if not args.remote:
        parser.error("--remote or HTUNNEL_REMOTE is required")
    if not token:
        parser.error("HTUNNEL_TOKEN environment variable is required")

    client = TunnelClient(
        args.remote, token, parse_local(args.local), args.local_timeout, args.concurrency
    )
    try:
        asyncio.run(client.run())
    except AuthError as err:
        logger.error("%s", err)
        raise SystemExit(1)
    except KeyboardInterrupt:
        logger.info("Stopped")


if __name__ == "__main__":
    main()
