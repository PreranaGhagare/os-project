"""FastAPI entry point for LibraOS."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from kernel.boot import Kernel
from server.websocket import handle_websocket

ROOT = Path(__file__).resolve().parents[1]


def create_app(kernel_instance: Kernel | None = None) -> FastAPI:
    active_kernel = kernel_instance if kernel_instance is not None else Kernel()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await active_kernel.boot()
        try:
            yield
        finally:
            active_kernel.save_disk_image()

    app = FastAPI(title="LibraOS", version="0.1.0-stage9", lifespan=lifespan)
    app.mount("/ui", StaticFiles(directory=ROOT / "ui"), name="ui")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(ROOT / "ui" / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": active_kernel.status, "name": "LibraOS"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await handle_websocket(websocket, active_kernel)

    return app


kernel = Kernel()
app = create_app(kernel)
