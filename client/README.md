# htunnel client

Connects to the htunnel relay server, receives your channel's webhooks over SSE, forwards each
one to your local app. The server has already answered the provider with `202`, so the
client only logs the local app's response.

## Setup

```bash
cd client
cp .env.example .env     # set HTUNNEL_REMOTE and HTUNNEL_TOKEN
uv sync
uv run --env-file .env python tunnel_client.py
```

On connect it prints your public webhook URL:

```
Tunnel connected (channel hung, client 3fd31cb9). Webhook URL: https://your-relay.onrender.com/webhook/hung/
```

Point your webhook provider at that URL plus any path. For example,
`.../webhook/hung/stripe?x=1` is forwarded to `http://localhost:8080/stripe?x=1`.

## Options

| Flag | Env var | Default | |
|---|---|---|---|
| `--remote` | `HTUNNEL_REMOTE` | **required** | Relay server base URL |
| – | `HTUNNEL_TOKEN` | **required** | Channel token. Env only, so it stays out of shell history |
| `--local` | `HTUNNEL_LOCAL` | `8080` | Local app port, or a full URL like `http://127.0.0.1:3000` |
| `--local-timeout` | `HTUNNEL_LOCAL_TIMEOUT` | `30` | Seconds to wait for the local app |
| `--concurrency` | `HTUNNEL_CONCURRENCY` | `10` | Max webhooks forwarded at once |
| `--verbose` | – | off | Debug logging |

Flags override env vars, e.g. `uv run --env-file .env python tunnel_client.py --local 3000`.

## Behaviour

- **Byte-exact bodies, repeated headers and the raw query string** reach the local app
  unchanged, so provider signature checks still work.
- **Concurrent forwarding**: a slow local request never blocks other webhooks.
- **Local results are logged only**: `INFO` for 2xx/3xx, `WARNING` for 4xx/5xx, and `ERROR`
  when the local app is unreachable or times out. A webhook that fails locally is not retried.
- **Reconnects** use exponential backoff with jitter (1s up to 30s). A connection that
  receives no data for 60s is treated as dead. The server pings every 15s.
- **Wrong token**: the client exits with code 1 instead of retrying.
- **Several clients on one channel**: each one forwards every webhook to its own local app.
