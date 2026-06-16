"""FastAPI backend for the OpenDSO2000 web UI.

The server connects to the scope (reusing the GUI-free ``Dso2000`` driver and
transports) and exposes:

* ``GET  /``               -> the single-page web UI
* ``GET  /api/devices``    -> discovered USB scopes + simulator options
* ``POST /api/connect``    -> connect to a chosen instrument
* ``POST /api/disconnect`` -> disconnect
* ``WS   /ws``             -> live binary waveform frames + JSON status out,
                              JSON control commands in

Waveform frames are min/max-downsampled to ~screen width and streamed as
``float32`` volts, so the browser renders the trace locally — only data crosses
the network, never pixels. This makes remote viewing (e.g. Pi server, Mac
browser) far lighter than VNC.

No Qt import here: the server runs headless on a Raspberry Pi with no desktop.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
from typing import Dict, List, Optional, Set

import numpy as np
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..scope.driver import Dso2000
from ..scope.enums import (AcquireType, Coupling, DdsType, EdgeSlope, FftWindow,
                           MathOperator, TimebaseMode, TriggerMode, TriggerSweep)
from ..scope.models import MODELS
from ..scope.processing import MathProcessor
from ..transport.discovery import list_devices
from ..transport.simulated import SimulatedTransport
from ..transport.usbtmc import UsbTmcTransport

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
RES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "res")

# Streaming downsample target (min/max pairs => 2x columns of points).
STREAM_COLUMNS = 700

# Measurements pushed when the table is enabled (scpi item, label, unit).
MEAS_ITEMS = [
    ("VPP", "Vpp", "V"), ("VMAX", "Vmax", "V"), ("VMIN", "Vmin", "V"),
    ("VAMP", "Vamp", "V"), ("VTOP", "Vtop", "V"), ("VBASe", "Vbase", "V"),
    ("VAVG", "Vavg", "V"), ("VRMS", "Vrms", "V"),
    ("OVERshoot", "Overshoot", "%"), ("PREShoot", "Preshoot", "%"),
    ("PERiod", "Period", "s"), ("FREQuency", "Freq", "Hz"),
    ("RTIMe", "Rise", "s"), ("FTIMe", "Fall", "s"),
    ("PWIDth", "+Width", "s"), ("NWIDth", "-Width", "s"),
    ("PDUTy", "+Duty", "%"), ("NDUTy", "-Duty", "%"),
]

# Optional shared secret; if OPENDSO2000_TOKEN is set, clients must supply it.
TOKEN = os.environ.get("OPENDSO2000_TOKEN", "")


def _minmax(v: np.ndarray, cols: int) -> np.ndarray:
    """Reduce a long trace to <=2*cols points preserving peaks (envelope)."""
    n = v.size
    if n <= 2 * cols:
        return v.astype("<f4")
    edges = np.linspace(0, n, cols + 1, dtype=int)
    out = np.empty(cols * 2, dtype="<f4")
    for i in range(cols):
        seg = v[edges[i]:edges[i + 1]]
        if seg.size:
            out[2 * i] = seg.min()
            out[2 * i + 1] = seg.max()
    return out


def encode_frame(wf, seq: int, math=None) -> bytes:
    chans = sorted(wf.channels)
    header = {"seq": seq, "srate": wf.sample_rate, "trig": bool(wf.triggered),
              "run": bool(wf.running), "channels": []}
    buffers: List[bytes] = []
    for ch in chans:
        tr = wf.channels[ch]
        v = _minmax(tr.volts, STREAM_COLUMNS)
        header["channels"].append({"ch": ch, "n": int(v.size),
                                   "scale": tr.scale, "offset": tr.offset})
        buffers.append(v.tobytes())
    if math is not None:
        # math is (x_div, y_div) already in division coordinates from
        # MathProcessor; stream the y envelope (x is implicit, -7..+7).
        y = _minmax(math[1].astype("float64"), STREAM_COLUMNS)
        header["math"] = {"n": int(y.size)}
        buffers.append(y.tobytes())
    hb = json.dumps(header).encode()
    return struct.pack("<I", len(hb)) + hb + b"".join(buffers)


class Session:
    """Holds the single active scope connection and streams to web clients."""

    def __init__(self) -> None:
        self.scope: Optional[Dso2000] = None
        self.clients: Set[WebSocket] = set()
        self.task: Optional[asyncio.Task] = None
        self.running = True
        self.fps = 30
        self.seq = 0
        self.measure_on = False
        self.label = ""
        self.math = MathProcessor()

    # -- connection ------------------------------------------------------

    async def connect(self, sel: dict) -> dict:
        await self.disconnect()
        if sel.get("kind") == "usb":
            vid = int(sel["vid"]); pid = int(sel["pid"])
            transport = UsbTmcTransport(vid, pid, serial=sel.get("serial"))
            self.label = sel.get("label", f"USB {vid:04x}:{pid:04x}")
        else:
            model = sel.get("model", "DSO2D15")
            transport = SimulatedTransport(model=model)
            self.label = f"Simulator — {model}"
        scope = Dso2000(transport)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, scope.connect)
        self.scope = scope
        self.running = True
        self.task = asyncio.create_task(self._acquire())
        spec = scope.spec
        return {
            "name": spec.name, "channels": spec.channels, "has_awg": spec.has_awg,
            "bandwidth": spec.bandwidth_mhz, "label": self.label, "idn": scope.idn,
            "volt_div_steps": list(spec.volt_div_steps),
            "time_div_steps": list(spec.time_div_steps),
            "memory_depths": list(spec.memory_depths),
            "awg_max_freq": spec.awg_max_freq,
            "measurements": [{"item": i, "label": l, "unit": u} for i, l, u in MEAS_ITEMS],
        }

    async def disconnect(self) -> None:
        if self.task:
            self.task.cancel()
            self.task = None
        if self.scope:
            sc = self.scope
            self.scope = None
            try:
                await asyncio.get_event_loop().run_in_executor(None, sc.disconnect)
            except Exception:
                pass

    # -- acquisition + broadcast ----------------------------------------

    async def _acquire(self) -> None:
        loop = asyncio.get_event_loop()
        meas_due = 0.0
        while self.scope is not None:
            if not self.running or not self.clients:
                await asyncio.sleep(0.05)
                continue
            try:
                wf = await loop.run_in_executor(None, self.scope.read_waveform)
            except Exception:
                await asyncio.sleep(0.2)
                continue
            if wf is not None:
                math = None
                if self.math.enabled:
                    try:
                        math = self.math.compute(wf)
                    except Exception:
                        math = None
                await self._broadcast(encode_frame(wf, self.seq, math))
                self.seq += 1
                await self._broadcast_json({"type": "status",
                                            "trig": "Triggered" if wf.triggered else "Auto",
                                            "srate": wf.sample_rate})
            # Measurements at ~1 Hz when the table is open.
            now = loop.time()
            if self.measure_on and now >= meas_due:
                meas_due = now + 1.0
                await self._push_measurements(loop)
            await asyncio.sleep(max(0.005, 1.0 / self.fps))

    async def _push_measurements(self, loop) -> None:
        if self.scope is None:
            return
        def fetch():
            data = {}
            for ch in range(1, self.scope.spec.channels + 1):
                if not self.scope.get_channel_enabled(ch):
                    continue
                vals = {}
                for item, _l, _u in MEAS_ITEMS:
                    v = self.scope.measure(ch, item)
                    vals[item] = None if v != v else v
                data[ch] = vals
            return data
        try:
            data = await loop.run_in_executor(None, fetch)
            await self._broadcast_json({"type": "meas", "data": data})
        except Exception:
            pass

    async def _broadcast(self, payload: bytes) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_bytes(payload)
            except Exception:
                self.clients.discard(ws)

    async def _broadcast_json(self, obj: dict) -> None:
        text = json.dumps(obj)
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                self.clients.discard(ws)

    # -- control dispatch ------------------------------------------------

    async def command(self, msg: dict) -> None:
        s = self.scope
        if s is None:
            return
        loop = asyncio.get_event_loop()

        async def call(fn, *a):
            await loop.run_in_executor(None, lambda: fn(*a))

        c = msg.get("cmd")
        try:
            if c == "run":
                self.running = bool(msg["on"])
                await call(s.run if self.running else s.stop)
            elif c == "single":
                self.running = True
                await call(s.set_trigger_sweep, TriggerSweep.SINGLE)
                await call(s.single)
            elif c == "autoset":
                await call(s.autoset)
            elif c == "force":
                await call(s.force_trigger)
            elif c == "fps":
                self.fps = max(1, min(int(msg["value"]), 120))
            elif c == "measure":
                self.measure_on = bool(msg["enabled"])
            elif c == "channel":
                ch = int(msg["ch"])
                if "display" in msg: await call(s.set_channel_enabled, ch, bool(msg["display"]))
                if "scale" in msg: await call(s.set_scale, ch, float(msg["scale"]))
                if "offset" in msg: await call(s.set_offset, ch, float(msg["offset"]))
                if "coupling" in msg: await call(s.set_coupling, ch, Coupling(msg["coupling"]))
                if "probe" in msg: await call(s.set_probe, ch, int(msg["probe"]))
                if "bw" in msg: await call(s.set_bandwidth_limit, ch, bool(msg["bw"]))
                if "invert" in msg: await call(s.set_invert, ch, bool(msg["invert"]))
            elif c == "timebase":
                if "scale" in msg: await call(s.set_timebase_scale, float(msg["scale"]))
                if "position" in msg: await call(s.set_timebase_position, float(msg["position"]))
                if "mode" in msg: await call(s.set_timebase_mode, TimebaseMode(msg["mode"]))
            elif c == "acquire":
                if "type" in msg: await call(s.set_acquire_type, AcquireType(msg["type"]))
                if "depth" in msg: await call(s.set_memory_depth, int(msg["depth"]))
            elif c == "trigger":
                if "mode" in msg: await call(s.set_trigger_mode, TriggerMode(msg["mode"]))
                if "sweep" in msg: await call(s.set_trigger_sweep, TriggerSweep(msg["sweep"]))
                if "source" in msg: await call(s.set_edge_source, msg["source"])
                if "slope" in msg: await call(s.set_edge_slope, EdgeSlope(msg["slope"]))
                if "level" in msg: await call(s.set_edge_level, float(msg["level"]))
                if "param" in msg: await call(s.set_trigger_param, msg["param"], msg["value"])
            elif c == "math":
                m = self.math
                if "enabled" in msg: m.enabled = bool(msg["enabled"])
                if "operator" in msg: m.operator = MathOperator(msg["operator"]).value
                if "source1" in msg: m.source1 = int(msg["source1"])
                if "source2" in msg: m.source2 = int(msg["source2"])
                if "scale" in msg: m.scale = float(msg["scale"])
                if "window" in msg: m.window = FftWindow(msg["window"]).value
                if "unit" in msg: m.unit = msg["unit"]
            elif c == "awg":
                if "on" in msg: await call(s.set_awg_enabled, bool(msg["on"]))
                if "type" in msg: await call(s.set_awg_type, DdsType(msg["type"]))
                if "freq" in msg: await call(s.set_awg_frequency, float(msg["freq"]))
                if "amp" in msg: await call(s.set_awg_amplitude, float(msg["amp"]))
                if "offset" in msg: await call(s.set_awg_offset, float(msg["offset"]))
                if "duty" in msg: await call(s.set_awg_duty, float(msg["duty"]))
            elif c == "mask":
                if "enabled" in msg: await call(s.set_mask_enabled, bool(msg["enabled"]))
                if "source" in msg: await call(s.set_mask_source, msg["source"])
                if "x" in msg: await call(s.set_mask_x, float(msg["x"]))
                if "y" in msg: await call(s.set_mask_y, float(msg["y"]))
                if msg.get("create"): await call(s.mask_create)
                if "stats" in msg: await call(s.set_mask_stats, bool(msg["stats"]))
                if "output" in msg: await call(s.set_mask_output, bool(msg["output"]))
            elif c == "zoom":
                if "enabled" in msg: await call(s.set_zoom_enabled, bool(msg["enabled"]))
                if "scale" in msg: await call(s.set_zoom_scale, float(msg["scale"]))
                if "position" in msg: await call(s.set_zoom_position, float(msg["position"]))
        except Exception:
            pass


session = Session()
app = FastAPI(title="OpenDSO2000")


def _auth_ok(request_token: Optional[str]) -> bool:
    return not TOKEN or request_token == TOKEN


def _nostore(path: str) -> FileResponse:
    # Avoid stale UI when the server is updated; assets are tiny.
    return FileResponse(path, headers={"Cache-Control": "no-store"})


@app.get("/")
async def index():
    return _nostore(os.path.join(STATIC, "index.html"))


@app.get("/static/app.js")
async def _app_js():
    return _nostore(os.path.join(STATIC, "app.js"))


@app.get("/static/style.css")
async def _style_css():
    return _nostore(os.path.join(STATIC, "style.css"))


@app.get("/api/icon")
async def icon():
    return FileResponse(os.path.join(RES, "icon_256.png"))


@app.get("/api/devices")
async def devices():
    out = []
    try:
        for d in list_devices():
            out.append({"kind": "usb", "vid": d.vid, "pid": d.pid,
                        "serial": d.serial, "label": d.label})
    except Exception:
        pass
    for name in MODELS:
        out.append({"kind": "sim", "model": name, "label": f"Simulator — {name}"})
    return {"devices": out}


@app.post("/api/connect")
async def connect(request: Request):
    sel = await request.json()
    if not _auth_ok(sel.get("token")):
        return JSONResponse({"error": "bad token"}, status_code=403)
    try:
        info = await session.connect(sel)
        return {"ok": True, "info": info}
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/disconnect")
async def disconnect():
    await session.disconnect()
    return {"ok": True}


@app.post("/api/decode")
async def decode_endpoint(request: Request):
    """Decode a freshly captured (full-resolution) frame on the host."""
    from ..scope import decode as decoder
    if session.scope is None:
        return JSONResponse({"error": "not connected"}, status_code=409)
    body = await request.json()
    loop = asyncio.get_event_loop()
    wf = await loop.run_in_executor(None, session.scope.read_waveform)
    if not wf or not wf.channels:
        return JSONResponse({"error": "no captured data"}, status_code=409)
    channels = {ch: tr.volts for ch, tr in wf.channels.items()}
    params = {k: body[k] for k in
              ("source", "sda", "scl", "baud", "width", "edge", "bit_order",
               "data_bits", "parity", "invert") if k in body}
    return decoder.decode(body.get("protocol", "uart"), channels,
                          wf.sample_rate, **params)


@app.get("/api/waveform.csv")
async def waveform_csv():
    """Full-resolution capture as CSV (time + each enabled channel in volts)."""
    if session.scope is None:
        return JSONResponse({"error": "not connected"}, status_code=409)
    loop = asyncio.get_event_loop()
    wf = await loop.run_in_executor(None, session.scope.read_waveform)
    if not wf or not wf.channels:
        return JSONResponse({"error": "no data"}, status_code=409)
    chans = sorted(wf.channels)
    import io
    buf = io.StringIO()
    buf.write("time_s," + ",".join(f"CH{c}_V" for c in chans) + "\n")
    t = wf.time
    cols = [wf.channels[c].volts for c in chans]
    n = min(len(t), *(len(v) for v in cols)) if cols else 0
    for i in range(n):
        buf.write(f"{t[i]:.9g}," + ",".join(f"{v[i]:.6g}" for v in cols) + "\n")
    from fastapi.responses import Response
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=opendso2000.csv"})


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    if not _auth_ok(ws.query_params.get("token")):
        await ws.close(code=4403)
        return
    session.clients.add(ws)
    try:
        while True:
            msg = await ws.receive_text()
            try:
                await session.command(json.loads(msg))
            except Exception:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        session.clients.discard(ws)


# Static assets (app.js, style.css, …) under /static.
app.mount("/static", StaticFiles(directory=STATIC), name="static")
