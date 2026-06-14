"""Enumerations mirroring the DSO2000 SCPI parameter vocabularies.

Values are exactly the SCPI tokens accepted/returned by the instrument so they
can be used directly when formatting commands or parsing query replies.
"""

from __future__ import annotations

from enum import Enum


class Coupling(str, Enum):
    AC = "AC"
    DC = "DC"
    GND = "GND"


class AcquireType(str, Enum):
    NORMAL = "NORMal"
    AVERAGE = "AVERage"
    PEAK = "PEAK"
    HIRES = "HRESolution"


class TimebaseMode(str, Enum):
    MAIN = "MAIN"   # YT
    XY = "XY"
    ROLL = "ROLL"


class TriggerMode(str, Enum):
    EDGE = "EDGE"
    PULSE = "PULSe"
    SLOPE = "SLOPe"
    TV = "TV"
    TIMEOUT = "TIMeout"
    WINDOW = "WINdow"
    PATTERN = "PATTern"
    INTERVAL = "INTerval"
    UNDERTHROW = "UNDerthrow"
    UART = "UART"
    LIN = "LIN"
    CAN = "CAN"
    SPI = "SPI"
    IIC = "IIC"


class TriggerSweep(str, Enum):
    AUTO = "AUTO"
    NORMAL = "NORMal"
    SINGLE = "SINGle"


class EdgeSlope(str, Enum):
    RISING = "RISIng"
    FALLING = "FALLing"
    EITHER = "EITHer"


class TriggerStatus(str, Enum):
    TRIGGERED = "TRIGed"
    NOT_TRIGGERED = "NOTRIG"


class MathOperator(str, Enum):
    ADD = "ADD"
    SUBTRACT = "SUBTract"
    MULTIPLY = "MULTiply"
    DIVIDE = "DIVision"
    FFT = "FFT"


class FftWindow(str, Enum):
    RECTANGLE = "RECTangle"
    HANNING = "HANNing"
    HAMMING = "HAMMing"
    BLACKMAN = "BLACkman"
    TRIANGLE = "TRIangle"
    FLATTOP = "FLATtop"


class Polarity(str, Enum):
    POSITIVE = "POSItive"
    NEGATIVE = "NEGAtive"


class TimeWhen(str, Enum):
    EQUAL = "EQUAl"
    NOT_EQUAL = "NEQUal"
    GREATER = "GREAt"
    LESS = "LESS"


class DdsType(str, Enum):
    SINE = "SINE"
    SQUARE = "SQUAre"
    RAMP = "RAMP"
    EXP = "EXP"
    NOISE = "NOISe"
    DC = "DC"
    ARB1 = "ARB1"
    ARB2 = "ARB2"
    ARB3 = "ARB3"
    ARB4 = "ARB4"


class DdsModType(str, Enum):
    AM = "AM"
    FM = "FM"


# Measurement items accepted by ``:MEASure:CHANnel<n>:ITEM``.  Order is the one
# documented in the SCPI manual; the leading "V" of "VMAX" is preserved.
MEASUREMENTS = (
    "VMAX", "VMIN", "VPP", "VTOP", "VBASe", "VAMP", "VAVG", "VRMS",
    "OVERshoot", "PREShoot", "MARea", "MPARea",
    "PERiod", "FREQuency", "RTIMe", "FTIMe", "PWIDth", "NWIDth",
    "PDUTy", "NDUTy", "RDELay", "FDELay", "RPHase", "FPHase",
    "TVMAX", "TVMIN", "PSLEWrate", "NSLEWrate",
    "VUPper", "VMID", "VLOWer", "VARIance", "PVRMS",
    "PPULses", "NPULses", "PEDGes", "NEDGes",
)

# Human-friendly labels for the most commonly used measurements.
MEASUREMENT_LABELS = {
    "VPP": "Vpp",
    "VMAX": "Vmax",
    "VMIN": "Vmin",
    "VAVG": "Vavg",
    "VRMS": "Vrms",
    "VAMP": "Vamp",
    "VTOP": "Vtop",
    "VBASe": "Vbase",
    "FREQuency": "Freq",
    "PERiod": "Period",
    "RTIMe": "Rise",
    "FTIMe": "Fall",
    "PWIDth": "+Width",
    "NWIDth": "-Width",
    "PDUTy": "+Duty",
    "NDUTy": "-Duty",
    "OVERshoot": "Overshoot",
    "PREShoot": "Preshoot",
}
