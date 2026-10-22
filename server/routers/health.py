from fastapi import APIRouter, Request

router = APIRouter()


@router.api_route("/", methods=["GET", "HEAD"])
async def handshake():
    """Root endpoint for providers that verify the server URL with a plain GET or HEAD."""
    return {
        "status": "ok",
    }


@router.get("/health")
async def health_check(request: Request):
    """Simple endpoint to verify server status and keep Render instance warm."""
    app_state = request.app.state
    return {
        "status": "ok",
        "connected_clients": sum(len(c) for c in app_state.clients.values()),
    }
