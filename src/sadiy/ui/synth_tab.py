"""The Synth tab: set the ADF4351 to a preset LO frequency or to your own, and read back what it was told.

It works through bench mode (the Pins tab owns the session): sweeping and setting the synthesizer by hand
exclude each other, and `sweepd` enforces the rules (outputs off while the PLL moves, an output turns on only
after lock and only on request, with a confirm that is asked every time). The ADF4351 can not be read over SPI
on this wiring, so the readback is what the last words written say, decoded, plus the live lock detect level.
The logic without Qt is in `synth_core.py`.
"""
from __future__ import annotations

from typing import Callable, Optional

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from ..core import freqplan
from . import synth_core as core
from .bench_tab import PinsTab


def _mono() -> QtGui.QFont:
    return QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)


class SynthTab(QtWidgets.QWidget):
    def __init__(self, pins: PinsTab, message: Callable[..., None]) -> None:
        super().__init__()
        self.pins = pins
        self._message = message
        self.info = core.LoInfo()
        self.presets: list = []
        self._shown_active: Optional[bool] = None
        self._readback_text = ""

        self.mode_btn = QtWidgets.QPushButton("Enter bench mode")
        self.mode_btn.setToolTip("Stops sweeping and takes over the board. The same switch as in the Pins tab.")
        self.mode_btn.clicked.connect(lambda _c=False: self._toggle_mode())
        self.mode_label = QtWidgets.QLabel()
        self.mode_label.setWordWrap(True)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.mode_btn)
        top.addWidget(self.mode_label, 1)

        # presets
        self.preset_list = QtWidgets.QListWidget()
        self.preset_list.setMinimumHeight(190)
        self.preset_list.currentRowChanged.connect(self._on_preset)
        self.preset_list.itemActivated.connect(lambda _item: self.apply())
        self.preset_note = QtWidgets.QLabel()
        self.preset_note.setWordWrap(True)
        col = QtWidgets.QVBoxLayout()
        col.addWidget(self.preset_list)
        col.addWidget(self.preset_note)
        presets_box = QtWidgets.QGroupBox("Presets (the LO frequency, not the RF input)")
        presets_box.setLayout(col)

        # settings
        self.freq_sb = QtWidgets.QDoubleSpinBox()
        self.freq_sb.setRange(freqplan.OUT_MIN_HZ / 1e6, freqplan.VCO_MAX_HZ / 1e6)
        self.freq_sb.setDecimals(6)
        self.freq_sb.setSingleStep(1.0)
        self.freq_sb.setSuffix(" MHz")
        self.freq_sb.setKeyboardTracking(False)
        self.freq_sb.setValue(100.0)
        self.freq_sb.valueChanged.connect(lambda _v: self._update_plan())
        self.power_cb = QtWidgets.QComboBox()
        for dbm in core.POWER_CHOICES_DBM:
            self.power_cb.addItem(f"{dbm:+d} dBm", dbm)
        self.rf_chk = QtWidgets.QCheckBox("Turn the main output (RFOUTA) on after lock")
        self.rf_chk.setToolTip("Off by default. When ticked, Apply asks for a confirm each time; the output turns on only if "
                               "the PLL locks. The other output of the pair must be terminated.")
        self.plan_label = QtWidgets.QLabel()
        self.plan_label.setWordWrap(True)
        self.apply_btn = QtWidgets.QPushButton("Apply")
        self.apply_btn.setToolTip("Outputs off, write R5..R0, wait for lock detect, then the output if ticked")
        self.apply_btn.clicked.connect(lambda _c=False: self.apply())
        self.off_btn = QtWidgets.QPushButton("RF off")
        self.off_btn.setToolTip("Both RF outputs off, always allowed")
        self.off_btn.clicked.connect(lambda _c=False: self.rf_off())
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("Frequency"), 0, 0)
        g.addWidget(self.freq_sb, 0, 1)
        g.addWidget(QtWidgets.QLabel("Output power"), 1, 0)
        g.addWidget(self.power_cb, 1, 1)
        g.addWidget(self.rf_chk, 2, 0, 1, 2)
        g.addWidget(self.plan_label, 3, 0, 1, 2)
        g.addWidget(self.apply_btn, 4, 0)
        g.addWidget(self.off_btn, 4, 1)
        settings_box = QtWidgets.QGroupBox("Setting")
        settings_box.setLayout(g)

        # readback
        self.readback = QtWidgets.QLabel()
        self.readback.setFont(_mono())
        self.readback.setWordWrap(True)
        self.readback.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        self.refresh_btn = QtWidgets.QPushButton("Read LD")
        self.refresh_btn.setToolTip("Reads the lock detect line and the state again")
        self.refresh_btn.clicked.connect(lambda _c=False: self.pins.poll())
        col = QtWidgets.QVBoxLayout()
        col.addWidget(self.readback)
        col.addWidget(self.refresh_btn, 0, QtCore.Qt.AlignmentFlag.AlignLeft)
        readback_box = QtWidgets.QGroupBox("Readback (words last written, decoded; the chip can not be read)")
        readback_box.setLayout(col)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(presets_box, 1)
        right = QtWidgets.QVBoxLayout()
        right.addWidget(settings_box)
        right.addWidget(readback_box)
        right.addStretch(1)
        body = QtWidgets.QHBoxLayout()
        body.addLayout(left, 1)
        body.addLayout(right, 1)
        outer = QtWidgets.QVBoxLayout(self)
        outer.addLayout(top)
        outer.addLayout(body, 1)

        self.set_info(self.info)
        self.show_readback(None)
        self.refresh()

    # ------------------------------------------------------------ what the receiver is
    def set_info(self, info: core.LoInfo) -> None:
        """New receiver data from sweepd's status: rebuild the presets (keeps the selection by name)."""
        self.info = info
        power = self.power_cb.currentData() if self.power_cb.count() else -4
        keep = self.presets[self.preset_list.currentRow()].name if 0 <= self.preset_list.currentRow() < len(self.presets) else None
        self.presets = core.presets(info, power)
        self.preset_list.blockSignals(True)
        self.preset_list.clear()
        for p in self.presets:
            self.preset_list.addItem(f"{p.name}    {p.f_lo_hz / 1e6:.3f} MHz")
        self.preset_list.blockSignals(False)
        names = [p.name for p in self.presets]
        if keep in names:
            self.preset_list.setCurrentRow(names.index(keep))
        elif self.presets:
            self.preset_list.setCurrentRow(0)
        self._update_plan()

    def _on_preset(self, row: int) -> None:
        if not 0 <= row < len(self.presets):
            return
        p = self.presets[row]
        self.freq_sb.blockSignals(True)
        self.freq_sb.setValue(p.f_lo_hz / 1e6)
        self.freq_sb.blockSignals(False)
        self.power_cb.setCurrentIndex(self.power_cb.findData(p.power_dbm))
        self.preset_note.setText(p.note)
        self._update_plan()

    def _update_plan(self) -> None:
        self.plan_label.setText(core.plan_text(self.freq_sb.value() * 1e6, self.info))

    # ------------------------------------------------------------ bench mode
    def _toggle_mode(self) -> None:
        self.pins.toggle_mode()
        self.refresh()

    def refresh(self) -> None:
        """Follow bench mode: the buttons work only while it is on. Cheap enough to call on every poll."""
        on = self.pins.session.active
        if on == self._shown_active:
            return
        self._shown_active = on
        self.mode_btn.setText("Leave bench mode" if on else "Enter bench mode")
        for w in (self.apply_btn, self.off_btn, self.refresh_btn):
            w.setEnabled(on)
        if on:
            limits = self.pins.session.limits or {}
            sim = " SIMULATED, no hardware is touched." if limits.get("simulated") else ""
            self.mode_label.setText(f"Bench mode on: {limits.get('backend', '')}.{sim} Leaving turns the RF outputs off.")
            self.mode_label.setStyleSheet("color:#c05000;font-weight:bold;")
        else:
            self.mode_label.setText("Bench mode off: the readback shows the sweep. Enter bench mode to set the synthesizer.")
            self.mode_label.setStyleSheet("")

    # ------------------------------------------------------------ actions
    def apply(self) -> None:
        if not self.pins.session.active:
            self._message("Enter bench mode first", warn=True)
            return
        reply = self.pins.session.set_synth(self.freq_sb.value() * 1e6, self.power_cb.currentData(), self.rf_chk.isChecked())
        if reply.get("ok"):
            f = reply["f_actual_hz"]
            locked = reply.get("locked")
            state = "locked" if locked else "NOT locked" if locked is False else "lock detect not available"
            if reply.get("note"):
                self._message(f"LO {f / 1e6:.6f} MHz, {state}: {reply['note']}", warn=True)
            else:
                rf = reply.get("rf", {})
                self._message(f"LO {f / 1e6:.6f} MHz, {state}, RF main {'ON' if rf.get('main') else 'off'}")
            self.pins.session.status["synth"] = reply.get("synth")
            self.show_readback(reply.get("synth"))
        elif not reply.get("cancelled"):
            self._message(reply.get("error", "refused"), warn=True)
        self.pins.poll()

    def rf_off(self) -> None:
        if not self.pins.session.active:
            self._message("Enter bench mode first", warn=True)
            return
        reply = self.pins.session.set_rf(False, False, self.power_cb.currentData())
        if reply.get("ok"):
            self._message("RF outputs off")
        else:
            self._message(reply.get("error", "refused"), warn=True)
        self.pins.poll()

    # ------------------------------------------------------------ readback
    def show_readback(self, synth: Optional[dict]) -> None:
        text = core.readback_text(synth)
        if text != self._readback_text:
            self._readback_text = text
            self.readback.setText(text)
