# OpenDSO2000

Client/server control software for Hantek DSO2000-series oscilloscopes. A server
connects to the scope over USB (USB-TMC / SCPI) and serves an HTML5 web UI;
control it from a browser on any device on the network. A built-in simulator
lets it run with no hardware attached.

## Supported hardware

### Oscilloscopes

| Model    | Bandwidth | Channels | Signal generator (AWG) |
|----------|-----------|----------|------------------------|
| DSO2C10  | 100 MHz   | 2        | no                     |
| DSO2C15  | 150 MHz   | 2        | no                     |
| DSO2D10  | 100 MHz   | 2        | yes (5 MHz, 1 ch)      |
| DSO2D15  | 150 MHz   | 2        | yes (5 MHz, 1 ch)      |

Common: 1 GSa/s real-time sampling, 8 M memory depth. The instruments present a
USB-TMC interface speaking SCPI and enumerate as USB id `049f:505e`.

### Platforms

- **Server:** macOS (Intel & Apple Silicon), Linux x86-64, Linux ARM/aarch64
  (incl. Raspberry Pi, runs headless), and Windows (x64).
- **Client:** any modern web browser (desktop or mobile).

## Requirements

- A prebuilt binary needs nothing else. To run from source: **Python 3.9+**.
- Python dependencies: `numpy`, `pyusb`, `libusb-package`, `fastapi`,
  `uvicorn[standard]`.
- USB access: a libusb runtime is **bundled** via `libusb-package`. Per-OS
  device access:
  - **Linux:** install the udev rule in `packaging/99-opendso2000.rules` and add
    your user to the `plugdev` group.
  - **Windows:** bind the scope to the **WinUSB** driver once with
    [Zadig](https://zadig.akeo.ie/) (USB id `049F:505E`).
  - **macOS:** none.

## Install

Download the binary for your scope host from the
[Releases](https://github.com/mbgroen/OpenDSO2000/releases) page, or run from
source:

```bash
git clone https://github.com/mbgroen/OpenDSO2000.git
cd OpenDSO2000
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Linux device permissions:

```bash
sudo cp packaging/99-opendso2000.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger   # then replug
```

The release `.app`/`.exe`/`.AppImage` are unsigned; on macOS first launch is
right-click → Open, and Linux AppImages need `chmod +x` (and possibly
`libfuse2`).

## Usage

```bash
python -m opendso2000                    # serve on http://0.0.0.0:8000/
python -m opendso2000 --port 9000 --open # custom port; open local browser
```

Open `http://<server-ip>:8000/` in a browser, pick an instrument (or a
simulator) in the connect dialog. Prebuilt binaries behave the same — running
one starts the server and opens the UI locally.

> **The server has no window** — it runs in the background and opens your
> browser. On macOS, double-clicking `OpenDSO2000.app` therefore shows no app
> window; it just opens the browser tab. Launching it a second time while it's
> already running (or running both the Intel and Apple-Silicon builds, which
> share a bundle id) yields macOS **error −47** ("already running / busy") —
> that's expected; the first instance is serving. Quit it from Activity Monitor
> (or `pkill -f OpenDSO2000`) before relaunching. For logs, run the binary from
> a terminal: `OpenDSO2000.app/Contents/MacOS/OpenDSO2000`. If Gatekeeper
> blocks the unsigned app, `xattr -cr OpenDSO2000.app` then right-click → Open.

Options and environment variables:

| Setting | Effect |
|---------|--------|
| `--host` / `--port` | bind address / port (default `0.0.0.0:8000`) |
| `--open` | open the local browser on start |
| `OPENDSO2000_MAX_FPS` | refresh-rate cap (also adjustable live in the UI) |
| `OPENDSO2000_TOKEN` | require `?token=…` on connect/WebSocket access |

## Functionality

- Live dual-channel display on a 14×8 division canvas (grid, per-channel
  colours, trigger level, cursors).
- **Vertical:** volts/div, position, coupling (AC/DC/GND), probe ratio,
  20 MHz bandwidth limit, invert, channel on/off.
- **Horizontal:** time/div, Y-T / X-Y / Roll, memory depth (4 K…8 M),
  acquisition mode (Normal/Average/Peak/Hi-Res).
- **Trigger:** edge, pulse, slope, video, timeout, window, interval, runt,
  pattern, and serial (UART/CAN/LIN/I²C/SPI), each with its full parameter set;
  Auto/Normal/Single sweep; force.
- **Run / Stop / Single / Auto-Set / Force.**
- **Math** (CH1±CH2, ×, ÷) and **FFT** (Hanning/Hamming/Blackman/Rectangle,
  dBV or Vrms), computed from full-resolution samples.
- **Horizontal position** (panel slider + draggable on-screen marker) and a
  trigger-status indicator (Trig'd / Auto / Stop).
- **Cursors** — manual X/Y/XY and **Track** (cursors ride the waveform), with
  draggable A/B handles and an on-screen ΔX / 1·ΔX / ΔY readout.
- **Measurement table** (Vpp, Vavg, Vrms, Vmax, Vmin, Freq, Period, Duty, …).
- **Pass/Fail mask** (source, X/Y tolerance, create, output).
- **Zoom / dual-window** — a magnified pane shows the highlighted region.
- **Protocol decode** — host-side decoding of **UART, I²C, SPI, CAN, LIN** from
  the captured samples (I²C/SPI use two channels; CAN does NRZ de-stuffing,
  standard + extended IDs). Accuracy depends on sample rate vs. bit rate; the
  panel warns when under-sampled.
- **Save / Recall** — PNG screenshot, full-resolution CSV export, setup JSON.
- **Signal generator** controls on the D-models (waveform, frequency,
  amplitude, offset, duty), with an optional **on-screen overlay** of the
  commanded output (blue) for quick input-vs-output comparison.
- Built-in **simulator** for every model.

### Not exposed by the instrument's SCPI interface

The following are device-screen-only features with no SCPI access, so they are
unavailable to any remote client: **DVM**, **frequency counter**, **reference
(REF) waveforms**, and **protocol-decode read-back**. Protocol *triggering* is
supported, and OpenDSO2000 performs protocol *decoding* itself from samples.

## APIs

The server exposes HTTP + WebSocket APIs (interactive OpenAPI docs at
`/docs`). The instrument driver is also usable directly from Python.

### HTTP

| Method & path | Purpose |
|---------------|---------|
| `GET /` | the web UI |
| `GET /api/devices` | list discovered USB scopes + simulator options |
| `POST /api/connect` | connect (`{kind:"usb"|"sim", …}`) → capabilities |
| `POST /api/disconnect` | disconnect |
| `POST /api/decode` | host-side protocol decode of a fresh capture |
| `GET /api/waveform.csv` | full-resolution capture as CSV |

### WebSocket `/ws`

- **Server → client (binary):** one frame per acquisition — a little-endian
  `uint32` header length, a JSON header (`seq`, `srate`, `trig`, per-channel
  `scale`/`offset`/`n`, optional `math`), then `float32` volts per channel
  (min/max-downsampled) and the optional math trace.
- **Server → client (text/JSON):** `{"type":"status"|"meas", …}`.
- **Client → server (text/JSON):** control commands `{"cmd": …}` —
  `run`, `single`, `autoset`, `force`, `fps`, `measure`, `channel`, `timebase`,
  `acquire`, `trigger`, `math`, `awg`, `mask`, `zoom`.

### Python driver

The `Dso2000` driver has no GUI/web dependency and can be scripted:

```python
from opendso2000.transport.discovery import open_first
from opendso2000.scope.driver import Dso2000

scope = Dso2000(open_first())     # first USB scope, else a simulator
scope.connect()
scope.set_timebase_scale(1e-3)
scope.set_scale(1, 0.5)
print(scope.measure(1, "VPP"))
wf = scope.read_waveform()        # decoded volts per channel
```

## Project layout

```
opendso2000/
├── transport/   USB-TMC layer (real + simulated) and device discovery
├── scope/       Instrument logic (no GUI): driver, models, waveform decode,
│                math/FFT processing, protocol decoders
├── server/      FastAPI app (REST + WebSocket) and the static web UI
└── res/         Icon assets
```

## Hardware calibration

The number of 8-bit ADC codes per vertical division is not stated in the SCPI
manual; the decoder assumes `CODES_PER_DIV = 25` (200 codes over 8 divisions,
centred on 128). If measured amplitudes are off by a constant factor on real
hardware, adjust that constant in `opendso2000/scope/waveform.py`.

## Trademarks & disclaimer

OpenDSO2000 is an independent, unofficial project, not affiliated with, endorsed
by, or sponsored by Qingdao Hantek Electronic Co., Ltd. "Hantek" and the model
names are trademarks of their owner, used only descriptively to identify
compatible instruments. No manufacturer logos or branding are bundled.

## License

GPL-3.0-or-later.
