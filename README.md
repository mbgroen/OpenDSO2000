# OpenDSO2000

Cross-platform **client/server** control software for the **Hantek
DSO2000-series** benchtop oscilloscopes:

| Model    | Bandwidth | Signal generator (AWG) |
|----------|-----------|------------------------|
| DSO2C10  | 100 MHz   | no                     |
| DSO2C15  | 150 MHz   | no                     |
| DSO2D10  | 100 MHz   | yes (5 MHz, 1 ch)      |
| DSO2D15  | 150 MHz   | yes (5 MHz, 1 ch)      |

A small **server** connects to the scope over USB (USB-TMC / SCPI, USB id
`049f:505e`) and serves an **HTML5 web UI**. Open it in any browser on the
network — so you can run the server on a Raspberry Pi wired to the scope and
drive it from your Mac, phone, or any other device.

These are **not** the EZ-USB FX2 PC scopes that
[OpenHantek](https://github.com/OpenHantek) supports; they are standalone
benchtop units needing a completely different client — which is this project.

Server runs on **macOS** (Intel & Apple Silicon), **Linux** (x86-64 & ARM, incl.
**Raspberry Pi**), and **Windows**. The client is any modern browser.

> **Status:** functionally complete against the published *DSO2000 Series SCPI
> Programmers Manual*, with a built-in simulator so it runs without hardware.
> The 8-bit sample scaling constant (`CODES_PER_DIV` in
> `opendso2000/scope/waveform.py`) is the one value to confirm against a real
> scope — see [Hardware calibration](#hardware-calibration).

## Why client/server

Streaming **waveform data** to the browser (which renders locally) is far
lighter than streaming **pixels** over VNC/remote desktop, so the UI stays
responsive even with the scope on a low-power Pi. Bonus: clients need no
install, and you can view from several devices at once.

## Features

- Live dual-channel Canvas display drawn like the instrument's 14×8 division
  screen (grid, colours, trigger line, cursors)
- **Vertical:** volts/div, position, coupling (AC/DC/GND), probe ratio,
  20 MHz bandwidth limit, invert, channel on/off
- **Horizontal:** time/div, Y-T / X-Y / Roll, memory depth (4 K…8 M),
  acquisition mode (Normal/Average/Peak/Hi-Res)
- **Trigger:** edge/pulse/slope/video/… types, Auto/Normal/Single sweep,
  source/slope/level, force
- **Run / Stop / Single / Auto-Set / Force**
- **Math** (CH1±CH2, ×, ÷) and **FFT** (Hanning/Hamming/Blackman/Rectangle,
  dBV or Vrms), computed server-side from full-resolution samples
- **Cursors** (manual X/Y/XY with ΔX, 1/ΔX, ΔY readout)
- **Measurement table** (Vpp, Vavg, Vrms, Vmax, Vmin, Freq, Period, Duty…)
- **Signal generator** controls on the D-models
- Adjustable refresh-rate cap (`OPENDSO2000_MAX_FPS`)
- Built-in **simulator** for every model — no hardware needed
- Optional access token (`OPENDSO2000_TOKEN`)

## Install (server)

Download the binary for your scope host from the
[Releases](https://github.com/mbgroen/OpenDSO2000/releases) page, or run from
source:

```bash
git clone https://github.com/mbgroen/OpenDSO2000.git
cd OpenDSO2000
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

USB backend (libusb) is bundled via `libusb-package`, so no system libusb is
normally required.

### Platform notes

- **Raspberry Pi / Linux ARM:** runs headless — no desktop needed. Install
  USB permissions: `sudo cp packaging/99-opendso2000.rules /etc/udev/rules.d/`
  then `sudo udevadm control --reload-rules && sudo udevadm trigger`, add
  yourself to `plugdev`, and replug the scope.
- **Linux x86-64:** same udev rule as above.
- **Windows:** bind the scope to **WinUSB** once with
  [Zadig](https://zadig.akeo.ie/) (USB id `049F:505E`); it runs in simulator
  mode without that.
- **macOS:** nothing extra; release `.app` is unsigned, so first launch is
  right-click → **Open**.

## Run

```bash
# On the machine connected to the scope:
python -m opendso2000                 # serves on http://0.0.0.0:8000/
python -m opendso2000 --port 9000 --open
```

Then open `http://<server-ip>:8000/` in a browser on any device, pick your
instrument (or a **Simulator**) in the connect dialog, and go. The bundled
binaries do the same — double-click opens the UI locally.

Useful options / environment:

- `--host` / `--port` — bind address and port
- `OPENDSO2000_MAX_FPS` — cap refresh rate (also live in the **Max FPS**
  control); lower it (e.g. `10`) for slow links
- `OPENDSO2000_TOKEN` — require `?token=…` for access

## Architecture

```
opendso2000/
├── transport/        USB-TMC layer (real + simulated) and discovery
│   ├── usbtmc.py       USB-TMC framing over PyUSB/libusb (bundled libusb)
│   ├── simulated.py    Fake instrument speaking the same SCPI dialect
│   └── discovery.py    Enumerate/open devices
├── scope/            Instrument logic (no GUI, scriptable)
│   ├── models.py       Model specs + capabilities + USB ids
│   ├── driver.py       Full SCPI driver (Dso2000)
│   ├── processing.py   Math/FFT host-side computation
│   └── waveform.py     :WAVeform:DATA:ALL? decoder
├── server/           FastAPI app + browser UI
│   ├── app.py          REST + WebSocket streaming, control dispatch
│   ├── __main__.py     uvicorn launcher
│   └── static/         index.html · app.js (Canvas scope) · style.css
└── res/              App icon assets
```

The driver has no GUI/web dependency, so it can also be scripted:

```python
from opendso2000.transport.discovery import open_first
from opendso2000.scope.driver import Dso2000

scope = Dso2000(open_first())
scope.connect()
scope.set_timebase_scale(1e-3)
print(scope.measure(1, "VPP"))
```

## Hardware calibration

The SCPI manual documents the command set and the `:WAVeform:DATA:ALL?` header
but not how many ADC codes map to one vertical division. The code uses the
conventional 8-bit value (`CODES_PER_DIV = 25`, i.e. 200 codes over 8 divisions,
centred on 128). If measured amplitudes are off by a constant factor on real
hardware, adjust that single constant in `opendso2000/scope/waveform.py`.

## Trademarks & disclaimer

OpenDSO2000 is an **independent, unofficial** project, **not affiliated with,
endorsed by, or sponsored by Qingdao Hantek Electronic Co., Ltd.** "Hantek" and
the model names are trademarks of their owner, used here only descriptively to
identify compatible instruments (nominative fair use). No manufacturer logos or
branding are bundled or displayed.

## License

GPL-3.0-or-later, in keeping with the OpenHantek lineage this work draws on.
