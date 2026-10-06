"""Authenticated noVNC front for the Docker embedded browser.

The VNC server and websockify only listen on 127.0.0.1 inside the container; this module is the only way
to reach them, and only with a valid Harbor-DL session (cookie) from the same origin.
"""
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

import websockets
from fastapi import Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

UPSTREAM = 'ws://127.0.0.1:6080'


def install(app, require_session, enabled, directory=None, upstream=None):
    """Registers /novnc/* and /websockify. require_session(request_or_websocket) raises HTTPException when not logged in."""
    root = Path(directory or os.environ.get('HARBOR_NOVNC_DIR') or '/usr/share/novnc')
    upstream = upstream or os.environ.get('HARBOR_VNC_WS') or UPSTREAM

    @app.get('/novnc/{path:path}')
    def novnc_file(path: str, account=Depends(require_session)):
        if not enabled():raise HTTPException(404, '内嵌浏览器仅在 Docker 模式提供')
        target = (root / (path or 'vnc_lite.html')).resolve()
        if not root.is_dir() or not target.is_relative_to(root.resolve()) or not target.is_file():
            raise HTTPException(404, '文件不存在')
        return FileResponse(target, headers={'Cache-Control': 'no-cache'})

    @app.websocket('/websockify')
    async def websockify(socket: WebSocket):
        origin = socket.headers.get('origin')
        try:require_session(socket)
        except HTTPException:
            await socket.close(code=4401);return
        if not enabled() or (origin and urlsplit(origin).netloc != socket.headers.get('host')):
            await socket.close(code=4403);return
        requested = socket.scope.get('subprotocols') or []
        await socket.accept(subprotocol='binary' if 'binary' in requested else None)
        try:
            async with websockets.connect(upstream, subprotocols=['binary'], max_size=None, open_timeout=5) as remote:
                async def up():
                    while True:
                        message = await socket.receive()
                        if message['type'] == 'websocket.disconnect':return
                        data = message.get('bytes')
                        if data is None:data = (message.get('text') or '').encode()
                        await remote.send(data)

                async def down():
                    async for data in remote:
                        if isinstance(data, str):await socket.send_text(data)
                        else:await socket.send_bytes(data)

                tasks = [asyncio.create_task(up()), asyncio.create_task(down())]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        except (OSError, websockets.WebSocketException, WebSocketDisconnect):pass
        finally:
            try:await socket.close()
            except RuntimeError:pass
