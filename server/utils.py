import json

from fastapi import HTTPException, Request

from config import MAX_BODY_BYTES

# Hop-by-hop headers (RFC 9110 §7.6.1) plus headers that are recomputed on each leg
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def read_limited_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large")

    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body too large")
        chunks.append(chunk)
    return b"".join(chunks)
