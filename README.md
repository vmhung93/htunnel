# htunnel

A small self-hosted webhook tunnel, like a minimal ngrok for webhooks. A public relay server
receives webhooks and streams them over Server-Sent Events to a tunnel client running on your
machine, which rebuilds each request and forwards it to your local app. The server answers the
provider with `202 Accepted` right away (fire-and-forget).

```
webhook provider ──► https://<host>/webhook/<channel>/<path>
                              │
                       [relay server]  ── SSE /connect (token → channel) ──►  tunnel client ──► localhost app
                              │
provider ◄── 202 Accepted ────┘   (immediately, without waiting for the local app)
```

## Features

- **Channels**: each person gets their own channel and token, so several people can share one
  server and each only sees their own webhooks.
- **Byte-exact bodies**: bodies travel base64-encoded, so provider signature checks
  (Stripe, GitHub, …) still pass.
- **Fails fast**: if nobody is connected to a channel, the caller gets `503` immediately.
  Nothing is queued or replayed later.
- **Several clients per channel**: every client on a channel gets each webhook.
- **Fire-and-forget**: providers get `202` at once, and slow local apps never cause provider
  timeouts. The flip side: the provider never sees the local app's response, so challenge
  handshakes (Slack, Meta, …) do not pass through.
- **Small**: FastAPI + uvicorn with all state in memory. Runs on Render's free tier.

## Repository layout

| Path | |
|---|---|
| [`server/`](server/) | Relay server. Protocol, endpoints and configuration are documented in [`server/README.md`](server/README.md) |
| [`client/`](client/) | Tunnel client. Options and behaviour are documented in [`client/README.md`](client/README.md) |

## Quick start (local)

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
cd server
cp .env.example .env          # then put real tokens in .env
uv sync
uv run --env-file .env python server.py
```

Check it is up:

```bash
curl http://localhost:10000/health
# {"status":"ok","connected_clients":0}
```

Until a client is connected to the channel, webhooks get `503`:

```bash
curl -i -X POST http://localhost:10000/webhook/user/test -d '{"hello":"world"}'
```

Then, in a second terminal, start the client (and your local app on port 8080):

```bash
cd client
cp .env.example .env          # HTUNNEL_REMOTE=http://localhost:10000, HTUNNEL_TOKEN=<your channel token>
uv sync
uv run --env-file .env python tunnel_client.py --local 8080
```

## Build and push the Docker image

The server image is built from [`server/Dockerfile`](server/Dockerfile). `.dockerignore` keeps
`server/.env` out of the image, so tokens are only ever passed when the container starts.

1. **Log in to Docker Hub** (once per machine):

   ```bash
   docker login
   ```

2. **Build** from the repo root. Tag a version and `latest`:

   ```bash
   DOCKER_USER=<dockerhub-user>
   VERSION=0.1.0

   docker build \
     -t $DOCKER_USER/htunnel:$VERSION \
     -t $DOCKER_USER/htunnel:latest \
     server
   ```

   On an Apple Silicon Mac, build for Render's `linux/amd64` servers instead:

   ```bash
   docker buildx build --platform linux/amd64 \
     -t $DOCKER_USER/htunnel:$VERSION \
     -t $DOCKER_USER/htunnel:latest \
     --push server          # builds and pushes in one step; skip step 4
   ```

3. **Test it locally** with your env file:

   ```bash
   docker run --rm -p 10000:10000 --env-file server/.env $DOCKER_USER/htunnel:latest
   curl http://localhost:10000/health      # in another terminal
   ```

4. **Push** both tags:

   ```bash
   docker push $DOCKER_USER/htunnel:$VERSION
   docker push $DOCKER_USER/htunnel:latest
   ```

5. **Releasing a new version:** bump `VERSION`, repeat steps 2 to 4, then redeploy on Render
   (see below).

The Docker Hub repository is public unless you make it private. That's fine as long as no
tokens are in the image, which `.dockerignore` takes care of.

## Deploy to Render

### Option A: from the Docker Hub image

1. Create a **Web Service** and choose **Existing image**:
   `docker.io/<dockerhub-user>/htunnel:latest` (or a specific `:<version>`).
   For a private repository, add your Docker Hub credentials in Render.
2. In **Environment**, add `CHANNEL_TOKENS` (see [`server/.env.example`](server/.env.example)).
   Render sets `PORT` itself. No build or start command is needed.
3. After pushing a new image, use **Manual Deploy → Deploy latest reference** in Render to
   pull it.

### Option B: from source

1. Create a **Web Service** from this repository.
2. Settings:
   - **Root directory:** `server`
   - **Build command:** `pip install uv && uv sync --frozen`
   - **Start command:** `uv run uvicorn server:app --host 0.0.0.0 --port $PORT --timeout-graceful-shutdown 5`
3. In **Environment**, add `CHANNEL_TOKENS`. Render sets `PORT` itself.

Either way, give each person their webhook URL
`https://<service>.onrender.com/webhook/<channel>/...` and their own token.

Notes for the free tier:

- Run **one instance and one worker**, since all state is in memory.
- Free services go to sleep after a period with no traffic, and the first request then waits
  for a cold start, which can be longer than some providers' webhook timeout. An external uptime
  monitor that hits `/health` every few minutes keeps the service awake.
- Restarts and deploys drop all connections, and the client reconnects automatically. The
  Docker image already sets the graceful-shutdown timeout. For Option B, keep
  `--timeout-graceful-shutdown` in the start command so the old process closes its SSE streams.

## Security

- Anyone with a channel's token receives that channel's webhooks, including headers and
  bodies. Give each person their own token and never commit `.env`.
- To revoke someone, remove their entry from `CHANNEL_TOKENS` and restart the service.
- `/webhook/...` is public by design (providers must reach it). Verify provider signatures
  in your local app as usual.
