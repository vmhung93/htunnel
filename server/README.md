# htunnel server

Self-hosted webhook relay. Public webhooks hit this server and are pushed to the channel's
tunnel clients over Server-Sent Events. The server is **fire-and-forget**: it answers the
caller with `202 Accepted` straight away and never waits for the local app.

```
caller --> POST /webhook/{channel}/{path} --> [server] --SSE /connect--> tunnel client --> local app
caller <-- 202 Accepted (immediately) ------ [server]
```

## Endpoints

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | – | Status and number of connected clients |
| `ANY /webhook/{channel}[/{path}]` | – | Public receiver (GET, POST, PUT, DELETE, PATCH, HEAD, OPTIONS) |
| `GET /connect` | Bearer | SSE stream of the token's channel: `webhook` and `ping` events |

Authenticated endpoints require `Authorization: Bearer <channel token>`.

## Channels

Each person gets their own channel and token, configured in `CHANNEL_TOKENS`
(e.g. `user1=token1,user2=token2`). The token decides the channel, so a client never
sends a channel name and cannot subscribe to someone else's channel.

- Point the webhook provider at `https://<host>/webhook/<channel>/<path>`.
- A client receives only its own channel's webhooks.
- Several clients on the same channel (e.g. two machines) all receive each webhook.
- To revoke someone, remove their entry from `CHANNEL_TOKENS` and restart.

## Protocol

`webhook` event data:

```json
{
  "request_id": "uuid",
  "method": "POST",
  "path": "/stripe",
  "headers": [["content-type", "application/json"], ["x-sig", "..."]],
  "query_string": "a=1&a=2",
  "body_b64": "base64 of the exact request bytes"
}
```

Headers are lists of pairs so repeated keys survive. Hop-by-hop headers and `content-length`
are dropped; the client recomputes them.

Status codes returned to the webhook caller:

- `202`: handed to every connected client of the channel, body `{"status": "accepted", "request_id": "..."}`
- `404`: the channel is not configured
- `503`: no client is connected to the channel. Nothing is queued, so most providers will retry later
- `413`: body larger than `MAX_BODY_BYTES`

Since the server does not wait, the caller never sees the local app's status code or body.
That means verification handshakes that must echo a value (Slack `url_verification`, Meta
`hub.challenge`, …) will not pass through the tunnel, and a local `500` does not make the
provider retry.

Nothing is retained between connections: events still queued when a client disconnects are
dropped and never replayed.

## Configuration

| Variable | Default | |
|---|---|---|
| `CHANNEL_TOKENS` | **required** | `channel=token` pairs, comma-separated. Channel names: `A-Z a-z 0-9 _ -`; tokens must be unique and contain no commas |
| `PORT` | `10000` | Listen port (set automatically on Render) |
| `HEARTBEAT_INTERVAL` | `15` | Seconds between SSE pings |
| `MAX_BODY_BYTES` | `5242880` | Max webhook body size |
| `LOG_LEVEL` | `INFO` | |

## Running

```bash
uv sync
cp .env.example .env && uv run --env-file .env python server.py
# or inline:
CHANNEL_TOKENS="user1=$(openssl rand -hex 32),user2=$(openssl rand -hex 32)" uv run python server.py
# or: CHANNEL_TOKENS=... uv run uvicorn server:app --host 0.0.0.0 --port 10000 --timeout-graceful-shutdown 5
```

State is held in memory, so run **exactly one worker and one instance**.

Always pass `--timeout-graceful-shutdown`: SSE streams never end on their own, so without it a
restarting server keeps old client connections open while the new process gets the webhooks.

## Docker

```bash
docker build -t <dockerhub-user>/htunnel-server:latest server   # from the repo root
docker run --rm -p 10000:10000 -e CHANNEL_TOKENS="user1=<token>" <dockerhub-user>/htunnel-server:latest
docker push <dockerhub-user>/htunnel-server:latest
```

The image runs `python server.py` as a non-root user and listens on `$PORT` (default `10000`).
`.env` is excluded by `.dockerignore`, so pass `CHANNEL_TOKENS` at runtime with `-e` or
`--env-file server/.env`. Never bake tokens into the image.

## Layout

| File | Contents |
|---|---|
| `server.py` | App setup, logging, in-memory state on `app.state`, router registration, entry point |
| `config.py` | Settings from environment variables, `CHANNEL_TOKENS` parsing |
| `connection.py` | `ClientConnection` (one SSE client and its event queue) |
| `dependencies.py` | `require_channel`: authenticates a token and returns its channel |
| `utils.py` | Header filters, SSE formatting, size-limited body reader |
| `routers/health.py` | `GET /health` |
| `routers/tunnel.py` | `GET /connect` SSE stream (token-protected) |
| `routers/webhook.py` | Public `/webhook/{channel}` receiver |
