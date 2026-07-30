"""FastAPI application factory and server launcher."""
from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from disco.server.routers import analysis, catalogs, images, render, session_api, tiles
from disco.server.session import store

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(store.upload_dir, exist_ok=True)
    yield
    print("\n[INFO] Cleaning temporary session state...")
    store.clear(wipe_disk=True)


def create_app() -> FastAPI:
    app = FastAPI(title="DISCO", version="1.3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[
            "X-DISCO-Width", "X-DISCO-Height", "X-DISCO-Min", "X-DISCO-Max",
            "X-DISCO-P995", "X-DISCO-P999", "X-DISCO-PixelScale",
            "X-DISCO-Decimation", "X-DISCO-FullWidth", "X-DISCO-FullHeight",
            "X-DISCO-TileSize", "X-DISCO-Level", "X-DISCO-TileX", "X-DISCO-TileY",
        ],
    )

    for r in (images.router, analysis.router, render.router, catalogs.router, session_api.router, tiles.router):
        app.include_router(r, prefix="/api")
        app.include_router(r)  # backward-compatible unprefixed routes

    assets = os.path.join(STATIC_DIR, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "images": len(store.images)}

    @app.get("/{full_path:path}")
    async def serve_react_app(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        potential = os.path.join(STATIC_DIR, full_path) if full_path else ""
        if full_path and os.path.isfile(potential):
            response = FileResponse(potential)
        else:
            index = os.path.join(STATIC_DIR, "index.html")
            if not os.path.isfile(index):
                return JSONResponse(
                    {"detail": "GUI static assets not built. Run: cd client && npm run build:disco"},
                    status_code=503,
                )
            response = FileResponse(index)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    return app


app = create_app()


def get_free_port(start: int = 8000) -> int:
    port = start
    while port < start + 200:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                port += 1
    raise RuntimeError("No free port found")


def start_server():
    port = get_free_port()
    url = f"http://127.0.0.1:{port}"
    print("\n" + "=" * 50)
    print("        DISCO GUI IS RUNNING")
    print(f"   URL: {url}")
    print("   Press Ctrl+C to stop the server safely")
    print("=" * 50 + "\n")

    def open_browser():
        time.sleep(1.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    start_server()
