"""Rasterize res/icon.svg into PNGs and platform icon bundles.

Run with the project's venv python:
    python tools/make_icons.py

Produces, under opendso2000/res/:
  icon_16/32/64/128/256/512/1024.png, icon.png (256), and (on macOS) icon.icns.
A Windows icon.ico is written if Pillow is available.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(HERE, "opendso2000", "res")
SVG = os.path.join(RES, "icon.svg")
SIZES = [16, 32, 64, 128, 256, 512, 1024]


def render(size: int) -> QImage:
    renderer = QSvgRenderer(SVG)
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    renderer.render(p)
    p.end()
    return img


def main() -> int:
    QGuiApplication(sys.argv[:1])
    paths = {}
    for s in SIZES:
        out = os.path.join(RES, f"icon_{s}.png")
        render(s).save(out, "PNG")
        paths[s] = out
    render(256).save(os.path.join(RES, "icon.png"), "PNG")
    print("PNG sizes written:", ", ".join(str(s) for s in SIZES))

    # macOS .icns via iconutil.
    if sys.platform == "darwin":
        with tempfile.TemporaryDirectory() as td:
            iconset = os.path.join(td, "icon.iconset")
            os.makedirs(iconset)
            mapping = [(16, "16x16"), (32, "16x16@2x"), (32, "32x32"),
                       (64, "32x32@2x"), (128, "128x128"), (256, "128x128@2x"),
                       (256, "256x256"), (512, "256x256@2x"), (512, "512x512"),
                       (1024, "512x512@2x")]
            for size, name in mapping:
                render(size).save(os.path.join(iconset, f"icon_{name}.png"), "PNG")
            icns = os.path.join(RES, "icon.icns")
            try:
                subprocess.run(["iconutil", "-c", "icns", iconset, "-o", icns],
                               check=True)
                print("Wrote", icns)
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                print("iconutil failed (skipping .icns):", exc)

    # Windows .ico via Pillow if present.
    try:
        from PIL import Image
        imgs = [Image.open(paths[s]) for s in (16, 32, 64, 128, 256)]
        imgs[0].save(os.path.join(RES, "icon.ico"), sizes=[(s, s) for s in (16, 32, 64, 128, 256)])
        print("Wrote icon.ico")
    except Exception as exc:
        print("Pillow not available (skipping .ico):", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
