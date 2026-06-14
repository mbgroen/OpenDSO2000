# OpenDSO2000

Cross-platform control software for the **Hantek DSO2000-series** benchtop
oscilloscopes:

| Model    | Bandwidth | Signal generator (AWG) |
|----------|-----------|------------------------|
| DSO2C10  | 100 MHz   | no                     |
| DSO2C15  | 150 MHz   | no                     |
| DSO2D10  | 100 MHz   | yes (5 MHz, 1 ch)      |
| DSO2D15  | 150 MHz   | yes (5 MHz, 1 ch)      |

These instruments are **not** the EZ-USB FX2 PC scopes that
[OpenHantek](https://github.com/OpenHantek) supports. They are standalone
benchtop units that expose a **USB-TMC / SCPI** interface (USB id `049f:505e`),
so they need a completely different client — which is what this project is.

Runs on **macOS (Intel & Apple Silicon)** and **Linux**.

> **Status:** functionally complete against the published *DSO2000 Series SCPI
> Programmers Manual*, with a built-in simulator so it runs without hardware.
> The 8-bit sample scaling constant (`CODES_PER_DIV` in
> `opendso2000/scope/waveform.py`) is the one value that should be confirmed
> against a real scope — see [Hardware calibration](#hardware-calibration).

## Features

- Live dual-channel display drawn like the instrument's own 14×8 division screen
- **Vertical:** volts/div, position, coupling (AC/DC/GND), probe ratio,
  20 MHz bandwidth limit, invert, channel on/off
- **Horizontal:** time/div, Y-T / X-Y / Roll modes, memory depth (4 K…8 M),
  acquisition mode (Normal/Average/Peak/Hi-Res)
- **Trigger:** edge (source/slope/level), pulse, slope, video types; Auto /
  Normal / Single sweep; force trigger; draggable on-screen trigger level
- **Run / Stop / Single / Auto-Set / Force**
- **Automatic measurements** (Vpp, Vavg, Vrms, Vmax, Vmin, Freq, Period, Duty…),
  the full SCPI measurement set is available in the driver
- **Math**: CH1±CH2, CH1×CH2, CH1÷CH2, drawn live on screen
- **FFT** spectrum (Hanning/Hamming/Blackman/Rectangle windows, dBV or Vrms)
- **Cursors**: manual X (time / 1÷ΔX) and Y (volts) with live ΔX/ΔY readout
- **Signal generator** panel on the D-models (waveform, frequency, amplitude,
  offset, duty, modulation, arbitrary upload)
- **Save screen image** to PNG
- Built-in **simulator** (`--simulate`) for development and demos

## Install

```bash
git clone <this repo>
cd OpenDSO2000
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Platform notes

**macOS (Intel / Apple Silicon)**

```bash
brew install libusb        # USB backend for pyusb
```

PySide6 ships native arm64 + x86_64 wheels, so the same install works on both.

**Linux**

```bash
sudo apt install libusb-1.0-0        # or your distro's equivalent
# Grant USB access without root:
sudo cp packaging/99-opendso2000.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Make sure your user is in the `plugdev` group, then replug the scope.

## Run

```bash
# With a scope connected over USB:
python -m opendso2000

# Without hardware (simulator):
python -m opendso2000 --simulate --model DSO2D15
```

If no device is found the app falls back to the simulator automatically.

## Architecture

```
opendso2000/
├── transport/        USB-TMC layer (real + simulated) and discovery
│   ├── base.py         Transport interface
│   ├── usbtmc.py       USB-TMC framing over PyUSB/libusb
│   ├── simulated.py    Fake instrument speaking the same SCPI dialect
│   └── discovery.py    Enumerate/open devices
├── scope/            Instrument logic (no GUI)
│   ├── models.py       Model specs + capabilities + USB ids
│   ├── enums.py        SCPI parameter vocabularies
│   ├── driver.py       Full SCPI driver (Dso2000)
│   ├── processing.py   Math/FFT + cursor host-side state (no GUI)
│   └── waveform.py     :WAVeform:DATA:ALL? decoder
├── acquisition.py    Background acquisition QThread
├── res/              App icon assets (svg, png, icns)
└── ui/               PySide6 device-styled interface
    ├── scopeview.py    pyqtgraph screen (division grid)
    ├── screen.py       Screen chrome (status + channel bars)
    ├── knob.py         Rotary front-panel knob
    ├── softkeys.py     On-screen F1–F6 menu strip
    ├── menus.py        Soft-key menu definitions
    ├── frontpanel.py   Hardware-style front panel
    └── app.py          Entry point
```

The driver has no GUI dependency, so it can also be scripted:

```python
from opendso2000.transport.discovery import open_first
from opendso2000.scope.driver import Dso2000

scope = Dso2000(open_first())
scope.connect()
scope.set_timebase_scale(1e-3)
print(scope.measure(1, "VPP"))
```

## Hardware calibration

The SCPI manual fully documents the command set and the `:WAVeform:DATA:ALL?`
header, but it does not state how many ADC codes correspond to one vertical
division. The code uses the conventional 8-bit value (`CODES_PER_DIV = 25`,
i.e. 200 codes across 8 divisions, centred on 128). If, on real hardware,
measured amplitudes are off by a constant factor, adjust that single constant
in `opendso2000/scope/waveform.py`. Everything else is driven by values
queried from the instrument.

## Trademarks & disclaimer

OpenDSO2000 is an **independent, unofficial** project and is **not affiliated
with, endorsed by, or sponsored by Qingdao Hantek Electronic Co., Ltd.**
"Hantek" and the model names (DSO2C10, DSO2C15, DSO2D10, DSO2D15, DSO2000) are
trademarks of their respective owner. They are used here **only descriptively**,
to identify the instruments this software is compatible with (nominative fair
use). No manufacturer logos or branding are bundled or displayed by the
application.

## License

GPL-3.0-or-later, in keeping with the OpenHantek lineage this work draws on.
