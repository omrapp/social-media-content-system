from fastapi import WebSocket, WebSocketDisconnect
import asyncio
import json
import time

_connections: list[WebSocket] = []


async def pipeline_ws(websocket: WebSocket):
    from backend.api.auth import verify_ws_token
    await websocket.accept()
    # Token arrives as first message body to keep JWT out of server access logs
    try:
        msg = await asyncio.wait_for(websocket.receive_json(), timeout=5.0)
        token = msg.get("token") if isinstance(msg, dict) else None
    except (asyncio.TimeoutError, Exception):
        token = None
    if not verify_ws_token(token):
        try:
            await websocket.close(code=4001)
        except Exception:
            pass
        return
    _connections.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except (WebSocketDisconnect, Exception):
        if websocket in _connections:
            _connections.remove(websocket)


async def broadcast(event: str, data: dict):
    message = json.dumps({"event": event, **data})
    dead = []
    for ws in _connections:
        try:
            await asyncio.wait_for(ws.send_text(message), timeout=2.0)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _connections:
            _connections.remove(ws)


async def broadcast_post_status(post_id: str, status: str, **extra) -> None:
    try:
        await broadcast("post_status", {"post_id": post_id, "status": status, **extra})
    except Exception:
        pass


async def log_broadcast(
    level: str,
    source: str,
    message: str,
    data: dict | None = None,
):
    try:
        await broadcast("log_event", {
            "level": level,
            "source": source,
            "message": message,
            "data": data or {},
            "ts": int(time.time() * 1000),
        })
    except Exception:
        pass
