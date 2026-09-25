"""
KEF LSX Web Control — FastAPI backend.

Reprend la logique async de main.py original (protocole binaire port 50001
avec préservation standby_time / orientation), expose une API REST + sert
le frontend statique. Pas d'USB (retiré comme demandé).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("kef")

# --- Configuration ----------------------------------------------------------

KEF_IP = os.environ.get("KEF_IP", "192.168.1.12")
KEF_PORT = int(os.environ.get("KEF_PORT", "50001"))
log.info("Configuré pour KEF LSX à %s:%d", KEF_IP, KEF_PORT)

# --- Mapping sources (USB retiré) -------------------------------------------

# Codes de base pour standby=20min, orientation L/R
INPUT_SOURCES_20_MINUTES_LR = {
    "Bluetooth": 9,
    "Aux": 10,
    "Opt": 11,
    "Wifi": 2,
}

STANDBY_OPTIONS = [20, 60, None]  # None = jamais

# Construit {source: {standby: (LR_code, RL_code)}}
INPUT_SOURCES: dict[str, dict[int | None, tuple[int, int]]] = {}
for _source, _code in INPUT_SOURCES_20_MINUTES_LR.items():
    _LR_mapping = {t: _code + i * 16 for i, t in enumerate(STANDBY_OPTIONS)}
    INPUT_SOURCES[_source] = {t: (LR, LR + 64) for t, LR in _LR_mapping.items()}

# Construit {code: (source, standby, orientation)} pour décodage
INPUT_SOURCES_RESPONSE: dict[int, tuple[str, int | None, str]] = {}
for _source, _mapping in INPUT_SOURCES.items():
    for _t, (_LR, _RL) in _mapping.items():
        INPUT_SOURCES_RESPONSE[_LR] = (_source, _t, "L/R")
        INPUT_SOURCES_RESPONSE[_RL] = (_source, _t, "R/L")

# Codes spéciaux (variantes observées dans aiokef)
INPUT_SOURCES_RESPONSE[48] = INPUT_SOURCES_RESPONSE.get(82, ("Wifi", 60, "R/L"))
INPUT_SOURCES_RESPONSE[15] = ("Bluetooth", 20, "L/R")  # Bluetooth_paired


# --- Connexion keep-alive ---------------------------------------------------

class KefConnection:
    """Connexion TCP keep-alive vers les enceintes KEF."""

    def __init__(self, host: str, port: int = 50001):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._disconnect_task: asyncio.Task | None = None
        self._keep_alive = 1.0

    def _schedule_disconnect(self) -> None:
        if self._disconnect_task is not None:
            self._disconnect_task.cancel()
        self._disconnect_task = asyncio.get_event_loop().create_task(self._delayed_disconnect())

    async def _delayed_disconnect(self) -> None:
        try:
            await asyncio.sleep(self._keep_alive)
            await self._disconnect()
        except asyncio.CancelledError:
            pass

    async def _disconnect(self) -> None:
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
        self._writer = None
        self._reader = None

    async def _ensure_connected(self) -> None:
        if self._disconnect_task is not None:
            self._disconnect_task.cancel()
            self._disconnect_task = None

        if self._writer is None or self._writer.is_closing():
            if self._writer is not None:
                await self._disconnect()
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port, family=socket.AF_INET),
                timeout=2.0,
            )

    async def send_command(self, cmd: bytes, retries: int = 5) -> bytes:
        async with self._lock:
            last_error: Exception | None = None
            for attempt in range(retries):
                try:
                    await self._ensure_connected()
                    assert self._writer and self._reader
                    self._writer.write(cmd)
                    await self._writer.drain()
                    data = await asyncio.wait_for(self._reader.read(100), timeout=2.0)
                    self._schedule_disconnect()
                    return data
                except Exception as e:
                    last_error = e
                    await self._disconnect()
                    if attempt < retries - 1:
                        await asyncio.sleep(0.4)
            assert last_error is not None
            raise last_error


kef_conn = KefConnection(KEF_IP, KEF_PORT)


# --- Logique haut-niveau ----------------------------------------------------

async def get_current_state() -> tuple[str, int | None, str, bool]:
    """(source, standby_time, orientation, is_on)."""
    response = await kef_conn.send_command(bytes([0x47, 0x30, 0x80]))
    raw_code = response[3]
    is_on = raw_code <= 128
    code = raw_code % 128
    if code in INPUT_SOURCES_RESPONSE:
        source, standby_time, orientation = INPUT_SOURCES_RESPONSE[code]
        return source, standby_time, orientation, is_on
    return "Unknown", 20, "L/R", is_on


async def set_source_preserving_settings(source_name: str) -> None:
    """Change la source en préservant standby_time et orientation."""
    if source_name not in INPUT_SOURCES:
        raise ValueError(f"Source inconnue: {source_name}")

    _, standby_time, orientation, _ = await get_current_state()
    if standby_time not in STANDBY_OPTIONS:
        standby_time = 20
    orientation_index = 0 if orientation == "L/R" else 1
    new_code = INPUT_SOURCES[source_name][standby_time][orientation_index] % 128
    await kef_conn.send_command(bytes([0x53, 0x30, 0x81, new_code]))


async def turn_off_preserving_settings() -> None:
    """Éteint en préservant tous les paramètres."""
    current_source, standby_time, orientation, _ = await get_current_state()
    if current_source not in INPUT_SOURCES:
        current_source = "Wifi"
    if standby_time not in STANDBY_OPTIONS:
        standby_time = 20
    # Bug KEF connu : crash si standby=20min lors de l'extinction
    if standby_time == 20:
        standby_time = 60
    orientation_index = 0 if orientation == "L/R" else 1
    code = INPUT_SOURCES[current_source][standby_time][orientation_index]
    off_code = (code % 128) + 128
    await kef_conn.send_command(bytes([0x53, 0x30, 0x81, off_code]))


async def get_volume() -> int:
    response = await kef_conn.send_command(bytes([0x47, 0x25, 0x80]))
    volume = response[3]
    if volume >= 128:
        volume -= 128
    return volume


async def set_volume(volume: int) -> None:
    volume = max(0, min(100, volume))
    await kef_conn.send_command(bytes([0x53, 0x25, 0x81, volume]))


# --- API FastAPI ------------------------------------------------------------

app = FastAPI(title="KEF LSX Web Control", version="1.0.0")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


class SourceRequest(BaseModel):
    source: str


class VolumeRequest(BaseModel):
    volume: int = Field(..., ge=0, le=100)


@app.get("/api/state")
async def api_state() -> dict:
    """Retourne l'état complet : source, volume, on/off, etc."""
    try:
        source, standby_time, orientation, is_on = await get_current_state()
        try:
            volume = await get_volume()
        except Exception:
            volume = None
        return {
            "online": True,
            "source": source,
            "standby_time": standby_time,
            "orientation": orientation,
            "is_on": is_on,
            "volume": volume,
            "available_sources": list(INPUT_SOURCES.keys()),
        }
    except Exception as e:
        log.warning("State check failed: %s", e)
        return {"online": False, "error": str(e)}


@app.post("/api/source")
async def api_set_source(req: SourceRequest) -> dict:
    try:
        await set_source_preserving_settings(req.source)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        log.error("set_source failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/volume")
async def api_set_volume(req: VolumeRequest) -> dict:
    try:
        await set_volume(req.volume)
        return {"ok": True}
    except Exception as e:
        log.error("set_volume failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/off")
async def api_off() -> dict:
    try:
        await turn_off_preserving_settings()
        return {"ok": True}
    except Exception as e:
        log.error("off failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


# Frontend statique
class NoCacheStaticFiles(StaticFiles):
    """Force la revalidation : sans ça le navigateur garde un app.js périmé."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response


app.mount("/static", NoCacheStaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, must-revalidate"},
    )
