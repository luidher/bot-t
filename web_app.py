from __future__ import annotations

import asyncio
import os
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import BotConfigUpdate
from core.runner import BotRunner


class WebSocketBroadcaster:
    def __init__(self) -> None:
        self.connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def add(self, websocket: WebSocket) -> None:
        self._loop = asyncio.get_running_loop()
        self.connections.append(websocket)

    def remove(self, websocket: WebSocket) -> None:
        if websocket in self.connections:
            self.connections.remove(websocket)

    def broadcast(self, data: dict[str, Any]) -> None:
        if not self.connections or self._loop is None:
            return

        async def send_to_all() -> None:
            for ws in list(self.connections):
                try:
                    await ws.send_json(data)
                except Exception:
                    self.remove(ws)

        try:
            asyncio.run_coroutine_threadsafe(send_to_all(), self._loop)
        except Exception as e:
            print(f"[ERROR] Error al transmitir por WebSocket: {e}")


app = FastAPI(title="Vision Bot Web Console")
broadcaster = WebSocketBroadcaster()
runner = BotRunner(event_callback=broadcaster.broadcast)


@app.get("/api/status")
def get_status():
    return runner.get_system_status()


@app.post("/api/config")
def update_config(new_config: BotConfigUpdate):
    config = runner.update_config(new_config)
    return {"success": True, "config": config}


@app.post("/api/run")
def trigger_run():
    if runner.loop_active:
        raise HTTPException(status_code=400, detail="El loop automatico ya se encuentra en ejecucion.")

    try:
        data = runner.run_once()
        return {"success": True, "data": data}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/screenshot/capture")
def trigger_capture():
    try:
        path = runner.capture_only()
        runner.log("Nueva captura de pantalla tomada.", "INFO")
        return {"success": True, "path": path}
    except Exception as e:
        runner.log(f"Error al tomar captura de pantalla: {e}", "ERROR")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.get("/api/screenshot/latest")
def get_latest_screenshot():
    latest_img = Path("screenshots/latest_web_capture.png")
    if latest_img.exists():
        return FileResponse(latest_img)

    screenshots = list(Path("screenshots").glob("screen_*.png"))
    if screenshots:
        newest = max(screenshots, key=os.path.getctime)
        return FileResponse(newest)

    raise HTTPException(status_code=404, detail="No se ha tomado ninguna captura aun.")


@app.post("/api/loop/start")
def start_loop():
    runner.start_loop()
    return {"success": True, "loop_running": True}


@app.post("/api/loop/stop")
def stop_loop():
    runner.stop_loop()
    return {"success": True, "loop_running": False}


@app.post("/api/confirm")
def handle_confirm(data: dict[str, Any]):
    approved = bool(data.get("approved", False))

    try:
        return runner.handle_confirm(approved)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        runner.log(f"Error al ejecutar el clic: {e}", "ERROR")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.post("/api/scroll")
def trigger_scroll(data: dict[str, Any]):
    amount = data.get("amount", runner.config.get("scroll_amount", -300))

    try:
        runner.execute_scroll_action(amount=int(amount))
        return {"success": True, "amount": amount}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    broadcaster.add(websocket)

    try:
        await websocket.send_json(
            {
                "type": "init",
                "config": runner.config,
                "loop_running": runner.loop_active,
                "pending_confirm": runner.pending_click_plan is not None,
                "last_run": runner.last_run_info,
            }
        )
        runner.log("Cliente web conectado.", "INFO")

        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        broadcaster.remove(websocket)
        print("[INFO] Cliente web desconectado.")
    except Exception as e:
        broadcaster.remove(websocket)
        print(f"[ERROR] Excepcion de WebSocket: {e}")


Path("screenshots").mkdir(exist_ok=True)
Path("web").mkdir(exist_ok=True)

app.mount("/screenshots", StaticFiles(directory="screenshots"), name="screenshots")
app.mount("/", StaticFiles(directory="web", html=True), name="web")


def open_browser_and_run() -> None:
    def target() -> None:
        time.sleep(1.5)
        webbrowser.open("http://localhost:8000")

    threading.Thread(target=target, daemon=True).start()


if __name__ == "__main__":
    import uvicorn

    open_browser_and_run()
    print("[START] Iniciando servidor en http://localhost:8000...")
    uvicorn.run("web_app:app", host="0.0.0.0", port=8000, log_level="info")
