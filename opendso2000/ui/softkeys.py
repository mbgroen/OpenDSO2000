"""On-screen soft-key menu system, mirroring the device's F1–F6 menu strip.

A :class:`Menu` is a title plus up to six :class:`MenuItem`s.  Each item shows a
label and its current value; pressing the corresponding soft-key runs the
item's action (cycle an option, toggle a flag, run a command) and the strip
re-reads every value so the display stays in sync.

The physical F1–F6 keys on the front panel are wired to :meth:`SoftkeyBar.press`,
so the menu can be driven either by clicking the on-screen keys or the panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from .style import ACCENT, PANEL_BG_LIGHT, TEXT, TEXT_DIM


@dataclass
class MenuItem:
    label: str
    value: Optional[Callable[[], str]] = None   # current value text
    action: Optional[Callable[[], None]] = None  # invoked on key press
    enabled: Callable[[], bool] = lambda: True


@dataclass
class Menu:
    title: str
    items: List[MenuItem] = field(default_factory=list)


class _SoftKey(QPushButton):
    def __init__(self, index: int):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._index = index
        self._label = QLabel("")
        self._value = QLabel("")
        self._label.setStyleSheet(f"color:{TEXT}; font-weight:600;")
        self._value.setStyleSheet(f"color:{ACCENT}; font-size:11px;")
        for lab in (self._label, self._value):
            lab.setAlignment(Qt.AlignCenter)
            lab.setWordWrap(True)
            lab.setAttribute(Qt.WA_TransparentForMouseEvents)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 4, 2, 4)
        lay.setSpacing(1)
        lay.addStretch(1)
        lay.addWidget(self._label)
        lay.addWidget(self._value)
        lay.addStretch(1)

    def set_content(self, label: str, value: str, active: bool):
        self._label.setText(label)
        self._value.setText(value)
        self.setVisible(active)


class SoftkeyBar(QFrame):
    """Vertical strip of six soft-keys drawn along the screen's right edge."""

    def __init__(self):
        super().__init__()
        self.setObjectName("softkeyBar")
        self.setFixedWidth(118)
        self.setStyleSheet(
            f"#softkeyBar {{ background: {PANEL_BG_LIGHT}; border-radius: 8px; }}"
            f" _SoftKey {{ }}"
        )
        self._title = QLabel("")
        self._title.setAlignment(Qt.AlignCenter)
        self._title.setStyleSheet(
            f"color:{TEXT}; font-weight:700; text-transform:uppercase;"
            f" font-size:10px; letter-spacing:1px; padding:4px;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(5)
        lay.addWidget(self._title)
        self._keys: List[_SoftKey] = []
        for i in range(6):
            k = _SoftKey(i)
            k.clicked.connect(lambda _=False, idx=i: self.press(idx))
            self._keys.append(k)
            lay.addWidget(k, 1)
        self._menu: Optional[Menu] = None

    def set_menu(self, menu: Optional[Menu]) -> None:
        self._menu = menu
        self.refresh()

    def current_menu(self) -> Optional[Menu]:
        return self._menu

    def press(self, index: int) -> None:
        if not self._menu or index >= len(self._menu.items):
            return
        item = self._menu.items[index]
        if item.action and item.enabled():
            item.action()
        self.refresh()

    def refresh(self) -> None:
        if not self._menu:
            self._title.setText("")
            for k in self._keys:
                k.set_content("", "", False)
            return
        self._title.setText(self._menu.title)
        for i, key in enumerate(self._keys):
            if i < len(self._menu.items):
                item = self._menu.items[i]
                val = item.value() if item.value else ""
                key.set_content(item.label, val, True)
                key.setEnabled(item.enabled())
            else:
                key.set_content("", "", False)
