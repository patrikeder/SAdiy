"""Spectrum analyzer front end: classic black display with graticule, soft controls on the right,
and an Advanced tab for the connection and for starting a simulated-hardware `sweepd`.

Run:   python -m sadiy.ui.sa_gui --sim           (simulated hardware on this PC)
       python -m sadiy.ui.sa_gui --host <bbb-ip> --connect

Needs the `ui` extra (PyQtGraph + PyQt5) and pyzmq. The GUI never touches hardware; it talks to
`sweepd` over ZeroMQ, so plotting can not disturb the SPI / GPIO timing.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import config as config_mod
from ..core.sweep import FLAGS_UNRELIABLE, flag_names
from ..logs import format_entry
from . import log_core
from . import sa_core as core
from .bench_tab import PinsTab
from .sim_runner import SimRunner
from .sweep_client import SweepClient

C_BG = "#000000"
C_GRID = "#1f6f1f"
C_TRACE_A = "#ffe600"
C_TRACE_B = "#38c8ff"
C_MARKER = "#ff5050"
C_TEXT = "#a8ffa8"

DEFAULT_TONES = ((True, 100.0, -30.0), (True, 250.0, -45.0), (False, 350.0, -60.0), (False, 60.0, -50.0))


# ---------------------------------------------------------------- small helpers

def _mono() -> QtGui.QFont:
    return QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)


def _dspin(lo, hi, val, step, decimals=3, suffix="") -> QtWidgets.QDoubleSpinBox:
    s = QtWidgets.QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(decimals)
    s.setSingleStep(step)
    s.setValue(val)
    if suffix:
        s.setSuffix(suffix)
    s.setKeyboardTracking(False)        # apply on Enter / arrows, not on every keystroke
    return s


def _ispin(lo, hi, val, step=1) -> QtWidgets.QSpinBox:
    s = QtWidgets.QSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(val)
    s.setKeyboardTracking(False)
    return s


def _quiet(widget, value) -> None:
    """Set a control without firing its change signal."""
    widget.blockSignals(True)
    if isinstance(widget, QtWidgets.QCheckBox):
        widget.setChecked(bool(value))
    elif isinstance(widget, QtWidgets.QComboBox):
        widget.setCurrentIndex(int(value))
    else:
        widget.setValue(value)
    widget.blockSignals(False)


def _group(title: str, layout: QtWidgets.QLayout) -> QtWidgets.QGroupBox:
    box = QtWidgets.QGroupBox(title)
    box.setLayout(layout)
    return box


def _button(text: str, slot, tip: str = "") -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    b.clicked.connect(lambda _checked=False: slot())
    if tip:
        b.setToolTip(tip)
    return b


# ---------------------------------------------------------------- display

class SpectrumView(pg.PlotWidget):
    """Black display with a 10 x 10 graticule, two traces and two markers."""

    def __init__(self, on_click) -> None:
        super().__init__(background=C_BG)
        self._on_click = on_click
        pi = self.getPlotItem()
        pi.hideAxis("left")
        pi.hideAxis("bottom")
        pi.hideButtons()
        pi.setMenuEnabled(False)
        pi.setMouseEnabled(x=False, y=False)
        pi.layout.setContentsMargins(0, 0, 0, 0)
        pi.vb.setDefaultPadding(0)
        pi.vb.disableAutoRange()
        self._pi = pi
        self._key = None

        self._grid = pg.PlotDataItem(pen=pg.mkPen(C_GRID, width=1))
        pi.addItem(self._grid)
        self._ylabels = []
        for k in range(core.DIVS + 1):
            anchor = (0.0, 0.0 if k == 0 else 1.0 if k == core.DIVS else 0.5)
            t = pg.TextItem("", color=C_TEXT, anchor=anchor)
            t.setFont(_mono())
            pi.addItem(t)
            self._ylabels.append(t)

        self.trace_b = pi.plot(pen=pg.mkPen(C_TRACE_B, width=1))
        self.trace_a = pi.plot(pen=pg.mkPen(C_TRACE_A, width=1))
        # points sweepd flagged as not reliable (PLL not locked, detector overload): red crosses on the trace
        self.bad = pi.plot(pen=None, symbol="x", symbolSize=8, symbolPen=pg.mkPen(C_MARKER, width=1), symbolBrush=None)
        self._marks = []
        for name in ("1", "2"):
            sc = pg.ScatterPlotItem(size=12, pen=pg.mkPen(None), brush=pg.mkBrush(C_MARKER), symbol="t")
            lab = pg.TextItem(name, color=C_MARKER, anchor=(0.5, 1.0))
            pi.addItem(sc)
            pi.addItem(lab)
            sc.setVisible(False)
            lab.setVisible(False)
            self._marks.append((sc, lab))
        self.scene().sigMouseClicked.connect(self._clicked)

    def _clicked(self, ev) -> None:
        if ev.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        vb = self._pi.vb
        if vb.sceneBoundingRect().contains(ev.scenePos()):
            second = bool(ev.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier)
            self._on_click(vb.mapSceneToView(ev.scenePos()).x(), second)

    def set_scale(self, start: float, stop: float, ref: float, dpd: float) -> None:
        key = (start, stop, ref, dpd)
        if key == self._key or not stop > start:
            return
        self._key = key
        ymin = ref - core.DIVS * dpd
        self._pi.setXRange(start, stop, padding=0)
        self._pi.setYRange(ymin, ref, padding=0)
        xs, ys = [], []
        for k in range(core.DIVS + 1):
            x = start + (stop - start) * k / core.DIVS
            xs += [x, x]
            ys += [ymin, ref]
            y = ref - k * dpd
            xs += [start, stop]
            ys += [y, y]
            self._ylabels[k].setText(f"{y:g}")
            self._ylabels[k].setPos(start, y)
        self._grid.setData(xs, ys, connect="pairs")

    def set_trace(self, which: str, f, p) -> None:
        item = self.trace_a if which == "a" else self.trace_b
        if p is None:
            item.setData([], [])
        else:
            item.setData(f, p, skipFiniteCheck=True)

    def set_bad(self, f, p, mask) -> None:
        if p is None or mask is None or not mask.any():
            self.bad.setData([], [])
        else:
            self.bad.setData(f[mask], p[mask], skipFiniteCheck=True)

    def set_marker(self, n: int, f: Optional[float], level: Optional[float], ref: float, dpd: float) -> None:
        sc, lab = self._marks[n]
        if f is None:
            sc.setVisible(False)
            lab.setVisible(False)
            return
        y = min(level + 0.45 * dpd, ref - 0.25 * dpd)
        sc.setData([f], [y])
        lab.setPos(f, min(y + 0.9 * dpd, ref))
        sc.setVisible(True)
        lab.setVisible(True)


# ---------------------------------------------------------------- main window

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, host: str = "127.0.0.1", pub_port: int = 5556, rep_port: int = 5557) -> None:
        super().__init__()
        self.setWindowTitle("SAdiy spectrum analyzer")
        self.limits = core.Limits()
        self.settings = core.SaSettings()
        self.client = SweepClient()
        self.runner = SimRunner()
        self.trace_a = core.TraceProcessor()
        self.trace_b = None                 # (axis, levels) stored with "Store B"
        self.flags_a = None                 # per-point flags behind trace A (or-ed over a hold / average)
        self.axis: Optional[core.Axis] = None
        self.last_atten = self.settings.atten_db
        self.rbw_hz = 230e3
        self.m = [core.Marker(), core.Marker()]
        self.sweep_period_s = 0.0
        self._last_t = None
        self._frames = 0
        self._single = False
        self._remote_running = True
        self._sync_tries = 0
        self.synced = False                 # settings and limits adopted from sweepd after connecting
        self._tick = 0
        self._sim_exit_reported = True
        self._sim_user_stopped = False
        self._log_len = -1
        self.dev_log = log_core.LogBuffer()  # what sweepd said (and what the GUI noted), Advanced tab
        self.dev_log_level = log_core.DEFAULT_LEVEL
        self._log_fetch_tries = 0
        self._bad_seen = 0
        self._last_note = None

        tabs = QtWidgets.QTabWidget()
        self.tabs = tabs
        attenuator = config_mod.load()["attenuator"]
        self.pins = PinsTab(self.client.request, self._stop, self._msg, attenuator["weights_db"], attenuator["active_high"])
        tabs.addTab(self._build_spectrum_tab(host), "Spectrum")
        tabs.addTab(self.pins, "Pins")
        self._advanced_page = self._build_advanced_tab(host, pub_port, rep_port)
        tabs.addTab(self._advanced_page, "Advanced")
        tabs.currentChanged.connect(lambda _i: self._update_log_badge())
        self.setCentralWidget(tabs)
        self.status_conn = QtWidgets.QLabel("not connected")
        self.status_msg = QtWidgets.QLabel("")
        self.status_warn = QtWidgets.QLabel("")
        self.status_warn.setStyleSheet("color:#c05000;")
        self.status_log = QtWidgets.QPushButton()
        self.status_log.setFlat(True)
        self.status_log.setStyleSheet("color:#c05000;")
        self.status_log.setToolTip("Unread errors and warnings in the device log (Advanced tab)")
        self.status_log.clicked.connect(lambda _c=False: self.tabs.setCurrentWidget(self._advanced_page))
        self.status_log.hide()
        self.statusBar().addWidget(self.status_conn)
        self.statusBar().addWidget(self.status_msg, 1)
        self.statusBar().addPermanentWidget(self.status_log)
        self.statusBar().addPermanentWidget(self.status_warn)

        self._refresh_controls()
        self._redraw()
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._poll)
        self.timer.start(self.poll_sb.value())
        self.resize(1280, 780)

    # ------------------------------------------------------------ spectrum tab

    def _build_spectrum_tab(self, host: str) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        outer = QtWidgets.QHBoxLayout(page)

        left = QtWidgets.QVBoxLayout()
        self.info = QtWidgets.QLabel()
        self.info.setFont(_mono())
        self.info.setStyleSheet(f"background:{C_BG}; color:{C_TEXT}; padding:3px;")
        self.view = SpectrumView(self._on_plot_click)
        self.lbl_start = QtWidgets.QLabel()
        self.lbl_center = QtWidgets.QLabel()
        self.lbl_stop = QtWidgets.QLabel()
        row = QtWidgets.QHBoxLayout()
        for lab, al in (
            (self.lbl_start, QtCore.Qt.AlignmentFlag.AlignLeft),
            (self.lbl_center, QtCore.Qt.AlignmentFlag.AlignHCenter),
            (self.lbl_stop, QtCore.Qt.AlignmentFlag.AlignRight),
        ):
            lab.setFont(_mono())
            lab.setAlignment(al)
            lab.setStyleSheet(f"background:{C_BG}; color:{C_TEXT}; padding:3px;")
            row.addWidget(lab, 1)
        self.readout = QtWidgets.QLabel()
        self.readout.setFont(_mono())
        self.readout.setMinimumHeight(62)
        self.readout.setStyleSheet(f"background:{C_BG}; color:{C_MARKER}; padding:3px;")
        left.addWidget(self.info)
        left.addWidget(self.view, 1)
        left.addLayout(row)
        left.addWidget(self.readout)
        outer.addLayout(left, 1)

        panel = QtWidgets.QWidget()
        pl = QtWidgets.QVBoxLayout(panel)
        pl.addWidget(self._build_freq_box())
        pl.addWidget(self._build_amp_box())
        pl.addWidget(self._build_sweep_box())
        pl.addWidget(self._build_trace_box())
        pl.addWidget(self._build_marker_box())
        pl.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(318)
        outer.addWidget(scroll)
        return page

    def _build_freq_box(self) -> QtWidgets.QGroupBox:
        self.center_sb = _dspin(0, 10000, 255, 1, 3, " MHz")
        self.span_sb = _dspin(0, 10000, 450, 10, 3, " MHz")
        self.start_sb = _dspin(0, 10000, 30, 1, 3, " MHz")
        self.stop_sb = _dspin(0, 10000, 480, 1, 3, " MHz")
        self.center_sb.valueChanged.connect(lambda _v: self._on_center_span())
        self.span_sb.valueChanged.connect(lambda _v: self._on_center_span())
        self.start_sb.valueChanged.connect(lambda _v: self._on_start_stop())
        self.stop_sb.valueChanged.connect(lambda _v: self._on_start_stop())
        g = QtWidgets.QGridLayout()
        for r, (name, w) in enumerate(
            (("Center", self.center_sb), ("Span", self.span_sb), ("Start", self.start_sb), ("Stop", self.stop_sb))
        ):
            g.addWidget(QtWidgets.QLabel(name), r, 0)
            g.addWidget(w, r, 1, 1, 3)
        g.addWidget(_button("Full span", self._full_span), 4, 0, 1, 2)
        g.addWidget(_button("Span ÷2", lambda: self._zoom(0.5)), 4, 2)
        g.addWidget(_button("Span ×2", lambda: self._zoom(2.0)), 4, 3)
        return _group("Frequency", g)

    def _build_amp_box(self) -> QtWidgets.QGroupBox:
        self.ref_sb = _dspin(-150, 30, self.settings.ref_dbm, 5, 1, " dBm")
        self.scale_cb = QtWidgets.QComboBox()
        for v in core.DB_PER_DIV_CHOICES:
            self.scale_cb.addItem(f"{v:g} dB/div", v)
        self.auto_att_chk = QtWidgets.QCheckBox("Auto")
        self.att_sb = _dspin(0, self.limits.atten_max_db, self.settings.atten_db, 0.5, 1, " dB")
        self.ref_sb.valueChanged.connect(lambda v: self._on_ref(v))
        self.scale_cb.currentIndexChanged.connect(lambda _i: self._on_scale())
        self.auto_att_chk.toggled.connect(lambda _c: self._on_atten())
        self.att_sb.valueChanged.connect(lambda _v: self._on_atten())
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("Ref level"), 0, 0)
        g.addWidget(self.ref_sb, 0, 1, 1, 2)
        g.addWidget(QtWidgets.QLabel("Scale"), 1, 0)
        g.addWidget(self.scale_cb, 1, 1, 1, 2)
        g.addWidget(QtWidgets.QLabel("Atten"), 2, 0)
        g.addWidget(self.att_sb, 2, 1)
        g.addWidget(self.auto_att_chk, 2, 2)
        g.addWidget(_button("Auto scale", self._auto_scale, "Fit reference level and dB/div to the trace"), 3, 0, 1, 3)
        return _group("Amplitude", g)

    def _build_sweep_box(self) -> QtWidgets.QGroupBox:
        self.points_sb = _ispin(2, 4001, self.settings.points, 100)
        self.avg_sb = _ispin(1, 64, self.settings.averages)
        self.points_sb.valueChanged.connect(lambda _v: self._on_sweep_params())
        self.avg_sb.valueChanged.connect(lambda _v: self._on_sweep_params())
        g = QtWidgets.QGridLayout()
        g.addWidget(_button("Run", self._run), 0, 0)
        g.addWidget(_button("Stop", self._stop), 0, 1)
        g.addWidget(_button("Single", self._single_sweep), 0, 2)
        g.addWidget(QtWidgets.QLabel("Points"), 1, 0)
        g.addWidget(self.points_sb, 1, 1, 1, 2)
        g.addWidget(QtWidgets.QLabel("Averages"), 2, 0)
        g.addWidget(self.avg_sb, 2, 1, 1, 2)
        g.addWidget(
            _button("Points = 2·span/RBW", self._auto_points, "Step of at most RBW/2, so narrow signals read right"),
            3, 0, 1, 3,
        )
        return _group("Sweep", g)

    def _build_trace_box(self) -> QtWidgets.QGroupBox:
        self.mode_cb = QtWidgets.QComboBox()
        for label, key in (
            ("Clear / Write", "clear_write"), ("Max hold", "max_hold"), ("Min hold", "min_hold"),
            ("Average", "average"), ("View", "view"), ("Blank", "blank"),
        ):
            self.mode_cb.addItem(label, key)
        self.mode_cb.currentIndexChanged.connect(lambda _i: self._on_trace_mode())
        self.show_b_chk = QtWidgets.QCheckBox("Show B")
        self.show_b_chk.toggled.connect(lambda _c: self._redraw())
        g = QtWidgets.QGridLayout()
        g.addWidget(self.mode_cb, 0, 0, 1, 3)
        g.addWidget(_button("Clear", self._clear_trace), 1, 0)
        g.addWidget(_button("Store B", self._store_b, "Copy trace A to the reference trace B"), 1, 1)
        g.addWidget(self.show_b_chk, 1, 2)
        return _group("Trace  (A yellow, B blue)", g)

    def _build_marker_box(self) -> QtWidgets.QGroupBox:
        self.m1_chk = QtWidgets.QCheckBox("M1")
        self.m2_chk = QtWidgets.QCheckBox("M2 (Δ)")
        self.track_chk = QtWidgets.QCheckBox("Track peak")
        self.m1_chk.toggled.connect(lambda c: self._on_marker_toggle(0, c))
        self.m2_chk.toggled.connect(lambda c: self._on_marker_toggle(1, c))
        g = QtWidgets.QGridLayout()
        g.addWidget(self.m1_chk, 0, 0)
        g.addWidget(self.m2_chk, 0, 1)
        g.addWidget(self.track_chk, 0, 2)
        g.addWidget(_button("Peak", self._peak), 1, 0)
        g.addWidget(_button("Next", lambda: self._next_peak("lower"), "Next lower peak"), 1, 1)
        g.addWidget(_button("Pk ←", lambda: self._next_peak("left")), 2, 0)
        g.addWidget(_button("Pk →", lambda: self._next_peak("right")), 2, 1)
        g.addWidget(_button("M→Center", self._marker_to_center), 3, 0)
        g.addWidget(_button("M→Ref", self._marker_to_ref), 3, 1)
        hint = QtWidgets.QLabel("Click the display: M1.  Shift+click: M2.")
        hint.setWordWrap(True)
        g.addWidget(hint, 4, 0, 1, 3)
        return _group("Marker", g)

    # ------------------------------------------------------------ advanced tab

    def _build_advanced_tab(self, host: str, pub_port: int, rep_port: int) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(page)

        # connection
        self.host_edit = QtWidgets.QLineEdit(host)
        self.pub_sb = _ispin(1, 65535, pub_port)
        self.rep_sb = _ispin(1, 65535, rep_port)
        self.connect_btn = _button("Connect", self._toggle_connect)
        self.conn_label = QtWidgets.QLabel("not connected")
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("sweepd host"), 0, 0)
        g.addWidget(self.host_edit, 0, 1)
        g.addWidget(QtWidgets.QLabel("Frame port (PUB)"), 0, 2)
        g.addWidget(self.pub_sb, 0, 3)
        g.addWidget(QtWidgets.QLabel("Command port (REP)"), 0, 4)
        g.addWidget(self.rep_sb, 0, 5)
        g.addWidget(self.connect_btn, 1, 0)
        g.addWidget(self.conn_label, 1, 1, 1, 5)
        col.addWidget(_group("Connection to sweepd", g))

        # device log: what sweepd reports. Low-level detail stays on the BBB (journalctl over ssh).
        self.dev_level_cb = QtWidgets.QComboBox()
        for label, level in log_core.LEVEL_CHOICES:
            self.dev_level_cb.addItem(label, level)
        self.dev_level_cb.setCurrentIndex([lv for _l, lv in log_core.LEVEL_CHOICES].index(log_core.DEFAULT_LEVEL))
        self.dev_level_cb.setToolTip("Lowest level shown. sweepd sends error, warning, info and debug.")
        self.dev_level_cb.currentIndexChanged.connect(lambda _i: self._on_dev_log_level())
        self.dev_pause_chk = QtWidgets.QCheckBox("Pause")
        self.dev_pause_chk.setToolTip("Stop adding lines (they are still kept); untick to catch up")
        self.dev_pause_chk.toggled.connect(lambda paused: None if paused else self._render_dev_log())
        self.dev_log_view = QtWidgets.QPlainTextEdit()
        self.dev_log_view.setReadOnly(True)
        self.dev_log_view.setFont(_mono())
        self.dev_log_view.setMaximumBlockCount(2000)
        self.dev_log_view.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        self.dev_log_view.setMinimumHeight(120)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Show"))
        row.addWidget(self.dev_level_cb)
        row.addWidget(self.dev_pause_chk)
        row.addWidget(_button("Clear", self._clear_dev_log))
        row.addWidget(_button("Save…", self._save_dev_log))
        row.addStretch(1)
        row.addWidget(QtWidgets.QLabel("Per point and per SPI word detail: sweepd -vv, read with journalctl -u sweepd -f over ssh"))
        v = QtWidgets.QVBoxLayout()
        v.addLayout(row)
        v.addWidget(self.dev_log_view, 1)
        col.addWidget(_group("Device log (messages from sweepd)", v), 1)

        # simulated hardware
        self.sim_btn = _button("Start simulated hardware", self._toggle_sim)
        self.sim_label = QtWidgets.QLabel("stopped")
        self.autoconnect_chk = QtWidgets.QCheckBox("Connect after start")
        self.autoconnect_chk.setChecked(True)
        self.period_sb = _dspin(0.0, 5.0, 0.1, 0.05, 2, " s")
        self.period_sb.setToolTip("Minimum time per sweep (sweepd --period)")
        self.noise_sb = _dspin(-160, -40, -100, 5, 0, " dBm")
        self.sim_rbw_sb = _dspin(10, 5000, 230, 10, 0, " kHz")
        self.tones = QtWidgets.QTableWidget(len(DEFAULT_TONES), 3)
        self.tones.setHorizontalHeaderLabels(["On", "Frequency (MHz)", "Level (dBm)"])
        self.tones.setMaximumHeight(32 * (len(DEFAULT_TONES) + 1))
        for r, (on, f, p) in enumerate(DEFAULT_TONES):
            chk = QtWidgets.QTableWidgetItem()
            chk.setFlags(QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsEnabled)
            chk.setCheckState(QtCore.Qt.CheckState.Checked if on else QtCore.Qt.CheckState.Unchecked)
            self.tones.setItem(r, 0, chk)
            self.tones.setItem(r, 1, QtWidgets.QTableWidgetItem(f"{f:g}"))
            self.tones.setItem(r, 2, QtWidgets.QTableWidgetItem(f"{p:g}"))
        self.tones.horizontalHeader().setStretchLastSection(True)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(_mono())
        self.log_view.setMaximumBlockCount(500)
        g = QtWidgets.QGridLayout()
        g.addWidget(self.sim_btn, 0, 0)
        g.addWidget(self.sim_label, 0, 1)
        g.addWidget(self.autoconnect_chk, 0, 2)
        g.addWidget(QtWidgets.QLabel("Sweep period"), 1, 0)
        g.addWidget(self.period_sb, 1, 1)
        g.addWidget(QtWidgets.QLabel("Noise floor (input)"), 2, 0)
        g.addWidget(self.noise_sb, 2, 1)
        g.addWidget(QtWidgets.QLabel("Simulated RBW"), 3, 0)
        g.addWidget(self.sim_rbw_sb, 3, 1)
        g.addWidget(QtWidgets.QLabel("Test tones (at the analyzer input; applied when the simulator starts)"), 1, 2, 1, 2)
        g.addWidget(self.tones, 2, 2, 3, 2)
        g.addWidget(self.log_view, 5, 0, 1, 4)
        g.setRowStretch(5, 1)
        col.addWidget(_group("Simulated hardware (sweepd --sim as a separate process on this PC)", g), 1)

        # analyzer
        self.rbw_sb = _dspin(1, 5000, 230, 10, 0, " kHz")
        self.rbw_sb.valueChanged.connect(lambda v: self._on_rbw(v))
        self.min_sb = _dspin(0, 10000, 30, 1, 3, " MHz")
        self.max_sb = _dspin(0, 10000, 480, 1, 3, " MHz")
        self.min_sb.valueChanged.connect(lambda _v: self._on_limits())
        self.max_sb.valueChanged.connect(lambda _v: self._on_limits())
        self.thr_sb = _dspin(1, 60, 6, 1, 0, " dB")
        self.thr_sb.setToolTip("Peak search only accepts peaks this far above the median level")
        self.avgn_sb = _ispin(2, 200, 10)
        self.avgn_sb.valueChanged.connect(lambda v: setattr(self.trace_a, "avg_count", int(v)))
        self.poll_sb = _ispin(10, 500, 30, 10)
        self.poll_sb.valueChanged.connect(lambda v: self.timer.setInterval(int(v)))
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("RBW for display and point count"), 0, 0)
        g.addWidget(self.rbw_sb, 0, 1)
        g.addWidget(QtWidgets.QLabel("Frequency limits"), 0, 2)
        g.addWidget(self.min_sb, 0, 3)
        g.addWidget(self.max_sb, 0, 4)
        g.addWidget(QtWidgets.QLabel("Peak threshold"), 1, 0)
        g.addWidget(self.thr_sb, 1, 1)
        g.addWidget(QtWidgets.QLabel("Sweeps in Average mode"), 1, 2)
        g.addWidget(self.avgn_sb, 1, 3)
        g.addWidget(QtWidgets.QLabel("GUI poll interval"), 2, 0)
        g.addWidget(self.poll_sb, 2, 1, 1, 1)
        g.addWidget(
            QtWidgets.QLabel("The limits are read from sweepd on connect; sweepd rejects ranges outside its own limits."),
            2, 2, 1, 3,
        )
        col.addWidget(_group("Analyzer", g))

        # data
        row = QtWidgets.QHBoxLayout()
        row.addWidget(_button("Save trace CSV…", self._save_csv))
        row.addWidget(_button("Save screenshot…", self._save_png))
        row.addStretch(1)
        col.addWidget(_group("Data", row))
        return page

    # ------------------------------------------------------------ messages / status

    def _msg(self, text: str, warn: bool = False, log: bool = True) -> None:
        self.status_msg.setText(text)
        self.status_msg.setStyleSheet("color:#c05000;" if warn else "")
        if warn and log:
            self._dev_note(logging.WARNING, text)      # the status bar forgets, the device log keeps it

    # ------------------------------------------------------------ device log

    def _dev_note(self, level: int, text: str) -> None:
        """A line from the GUI itself in the device log (connection events, status-bar warnings)."""
        if (level, text) == self._last_note:
            return
        self._last_note = (level, text)
        self._show_log_entries([self.dev_log.note(level, text)])

    def _show_log_entries(self, entries) -> None:
        """New entries: append the ones the level box allows (unless paused), update the counters."""
        if not entries:
            return
        if not self.dev_pause_chk.isChecked():
            for e in entries:
                if e.level >= self.dev_log_level:
                    self.dev_log_view.appendHtml(log_core.entry_html(e))
        for e in entries:
            if e.name != log_core.LOCAL_NAME and e.level >= logging.ERROR and not e.repeats:
                self._msg(f"sweepd: {e.msg}", warn=True, log=False)
        self._update_log_badge()

    def _render_dev_log(self) -> None:
        self.dev_log_view.setUpdatesEnabled(False)
        self.dev_log_view.clear()
        for e in self.dev_log.visible(self.dev_log_level):
            self.dev_log_view.appendHtml(log_core.entry_html(e))
        self.dev_log_view.setUpdatesEnabled(True)
        bar = self.dev_log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_dev_log_level(self) -> None:
        self.dev_log_level = int(self.dev_level_cb.currentData())
        self._render_dev_log()

    def _clear_dev_log(self) -> None:
        self.dev_log.clear()
        self._render_dev_log()
        self._update_log_badge()

    def _update_log_badge(self) -> None:
        if self.tabs.currentWidget() is self._advanced_page:
            self.dev_log.mark_seen()                  # it is on screen: nothing is unread
        badge = self.dev_log.badge
        self.tabs.setTabText(self.tabs.indexOf(self._advanced_page), "Advanced" + badge)
        self.status_log.setText(badge.strip(" ()"))
        self.status_log.setVisible(bool(badge))

    def _poll_dev_log(self) -> None:
        """Live records from the socket; a fetch from sweepd when there is a gap (connect, lost record)."""
        live = self.client.take_logs()
        if self.client.bad_frames != self._bad_seen:
            self._bad_seen = self.client.bad_frames
            self._dev_note(logging.WARNING, f"{self._bad_seen} undecodable message(s) from sweepd (version mismatch?)")
        if not self.client.connected:
            return
        if not self.dev_log.gap:
            self._show_log_entries(self.dev_log.add_live(live))
        elif self.synced and self._tick % 10 == 0 and self._log_fetch_tries < 5:
            got = self.client.fetch_log(self.dev_log.last_seq, 150)
            if got is None:
                self._log_fetch_tries += 1
                if self._log_fetch_tries == 5:
                    self._dev_note(logging.WARNING, "sweepd sent no log: it may be an older version without one")
            else:
                self._log_fetch_tries = 0
                self._show_log_entries(self.dev_log.add_fetched(*got))

    def _save_dev_log(self) -> None:
        default = str(Path("captures") / time.strftime("devlog-%Y%m%d-%H%M%S.txt"))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save device log", default, "Text (*.txt)")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text("\n".join(format_entry(e, with_date=True) for e in self.dev_log.entries) + "\n")
            self._msg(f"Saved {path}")

    def _set_conn(self, text: str) -> None:
        self.status_conn.setText(text)
        self.conn_label.setText(text)

    # ------------------------------------------------------------ controls <-> settings

    def _refresh_controls(self) -> None:
        s = self.settings
        _quiet(self.center_sb, s.center_hz / 1e6)
        _quiet(self.span_sb, s.span_hz / 1e6)
        _quiet(self.start_sb, s.start_hz / 1e6)
        _quiet(self.stop_sb, s.stop_hz / 1e6)
        _quiet(self.ref_sb, s.ref_dbm)
        _quiet(self.scale_cb, core.DB_PER_DIV_CHOICES.index(s.db_per_div))
        _quiet(self.auto_att_chk, s.auto_atten)
        self.att_sb.setMaximum(self.limits.atten_max_db)
        _quiet(self.att_sb, self.last_atten if s.auto_atten else s.atten_db)
        self.att_sb.setEnabled(not s.auto_atten)
        self.points_sb.setMaximum(self.limits.max_points)
        _quiet(self.points_sb, s.points)
        _quiet(self.avg_sb, s.averages)
        _quiet(self.min_sb, self.limits.rf_min_hz / 1e6)
        _quiet(self.max_sb, self.limits.rf_max_hz / 1e6)

    def _push(self) -> None:
        """Send the sweep settings to sweepd. If it rejects them, show why and re-sync."""
        if not self.client.connected:
            return
        r = self.client.request(self.settings.to_command())
        if r is None:
            self._msg("No reply from sweepd (is it running?)", warn=True)
        elif not r.get("ok"):
            self._msg(f"sweepd: {r.get('error', 'rejected')}", warn=True)
            self._sync_from_server()
        else:
            self._msg("")

    def _sync_from_server(self, timeout_ms: int = 500) -> bool:
        r = self.client.request({"cmd": "status"}, timeout_ms)
        if not r or not r.get("ok"):
            return False
        self.limits.apply_server(r.get("limits", {}))
        self.settings.apply_server(r.get("settings", {}))
        self._remote_running = bool(r.get("running", True))
        self.synced = True
        self.last_atten = self.settings.atten_db
        self._refresh_controls()
        self._redraw()
        return True

    def _after_freq_change(self) -> None:
        self._refresh_controls()
        self._push()
        self._redraw()

    def _on_center_span(self) -> None:
        self.settings.set_center_span(self.center_sb.value() * 1e6, self.span_sb.value() * 1e6, self.limits)
        self._after_freq_change()

    def _on_start_stop(self) -> None:
        self.settings.set_start_stop(self.start_sb.value() * 1e6, self.stop_sb.value() * 1e6, self.limits)
        self._after_freq_change()

    def _full_span(self) -> None:
        self.settings.set_start_stop(self.limits.rf_min_hz, self.limits.rf_max_hz, self.limits)
        self._after_freq_change()

    def _zoom(self, factor: float) -> None:
        self.settings.set_center_span(self.settings.center_hz, self.settings.span_hz * factor, self.limits)
        self._after_freq_change()

    def _on_ref(self, v: float) -> None:
        self.settings.ref_dbm = float(v)
        self._redraw()

    def _on_scale(self) -> None:
        self.settings.db_per_div = float(self.scale_cb.currentData())
        self._redraw()

    def _on_atten(self) -> None:
        self.settings.auto_atten = self.auto_att_chk.isChecked()
        if not self.settings.auto_atten:
            # leaving auto: keep the value that was in use, unless the operator just typed another
            self.settings.atten_db = self.att_sb.value()
        self.att_sb.setEnabled(not self.settings.auto_atten)
        self._push()
        self._redraw()

    def _on_sweep_params(self) -> None:
        self.settings.set_points(self.points_sb.value(), self.limits)
        self.settings.averages = self.avg_sb.value()
        self._push()
        self._redraw()

    def _auto_points(self) -> None:
        self.settings.points = core.recommended_points(self.settings.span_hz, self.rbw_hz, self.limits.max_points)
        self._refresh_controls()
        self._push()
        self._redraw()

    def _auto_scale(self) -> None:
        if self.trace_a.data is None:
            return
        self.settings.ref_dbm, self.settings.db_per_div = core.autoscale(self.trace_a.data)
        self._refresh_controls()
        self._redraw()

    def _on_rbw(self, khz: float) -> None:
        self.rbw_hz = float(khz) * 1e3
        self._redraw()

    def _on_limits(self) -> None:
        self.limits.rf_min_hz = self.min_sb.value() * 1e6
        self.limits.rf_max_hz = max(self.max_sb.value() * 1e6, self.limits.rf_min_hz + self.limits.min_span_hz)
        self.settings.set_start_stop(self.settings.start_hz, self.settings.stop_hz, self.limits)
        self._refresh_controls()

    # ------------------------------------------------------------ run control

    def _run(self) -> None:
        r = self.client.request({"cmd": "run"})
        if r is not None and r.get("ok"):
            self._remote_running = True
        elif r is not None:
            self._single = False
            self._msg(f"sweepd: {r.get('error', 'rejected')}", warn=True)
        self._redraw()

    def _stop(self) -> None:
        self._single = False
        if self.client.request({"cmd": "stop"}) is not None:
            self._remote_running = False
        self._redraw()

    def _single_sweep(self) -> None:
        self._single = True
        self._run()

    # ------------------------------------------------------------ traces and markers

    def _on_trace_mode(self) -> None:
        self.trace_a.set_mode(self.mode_cb.currentData())
        self._redraw()

    def _clear_trace(self) -> None:
        self.trace_a.reset()
        self._redraw()

    def _store_b(self) -> None:
        if self.axis is not None and self.trace_a.data is not None:
            self.trace_b = (self.axis, self.trace_a.data.copy())
            _quiet(self.show_b_chk, True)
            self._redraw()

    def _marker_check(self, n: int) -> QtWidgets.QCheckBox:
        return (self.m1_chk, self.m2_chk)[n]

    def _on_marker_toggle(self, n: int, on: bool) -> None:
        if on and self.axis is not None and self.trace_a.data is not None:
            if not self.m[n].enabled or self.m[n].index_in(self.axis) is None:
                self.m[n].place(self.axis, core.peak_index(self.trace_a.data) if n == 0 else self.axis.n // 2)
        self.m[n].enabled = on
        self._redraw()

    def _place(self, n: int, i: int) -> None:
        self.m[n].place(self.axis, i)
        _quiet(self._marker_check(n), True)
        self._redraw()

    def _on_plot_click(self, f_hz: float, second: bool) -> None:
        if self.axis is None:
            return
        i = self.axis.index_of(f_hz)
        if i is not None:
            self._place(1 if second else 0, i)

    def _peak(self) -> None:
        if self.axis is not None and self.trace_a.data is not None:
            self._place(0, core.peak_index(self.trace_a.data))

    def _next_peak(self, mode: str) -> None:
        if self.axis is None or self.trace_a.data is None:
            return
        cur = self.m[0].index_in(self.axis)
        if cur is None:
            self._peak()
            return
        sep = core.min_separation_bins(self.rbw_hz, self.axis.step_hz)
        j = core.next_peak(self.trace_a.data, cur, mode, sep, self.thr_sb.value())
        if j is None:
            self._msg("No further peak above the threshold", warn=True)
        else:
            self._msg("")
            self._place(0, j)

    def _marker_to_center(self) -> None:
        if self.m[0].enabled:
            self.settings.set_center_span(self.m[0].f_hz, self.settings.span_hz, self.limits)
            self._after_freq_change()

    def _marker_to_ref(self) -> None:
        if self.axis is None or self.trace_a.data is None:
            return
        i = self.m[0].index_in(self.axis)
        if i is not None:
            self.settings.ref_dbm = float(np.ceil(self.trace_a.data[i]))
            self._refresh_controls()
            self._redraw()

    # ------------------------------------------------------------ frames and drawing

    def _poll(self) -> None:
        self._tick += 1
        if self._tick % 10 == 0:
            self._update_sim_status()
        frame = self.client.poll_latest()
        self._poll_dev_log()
        if frame is not None:
            self.handle_frame(*frame, flags=self.client.last_flags)

    def handle_frame(self, header: dict, p, flags=None) -> None:
        axis = core.Axis.from_header(header)
        self.axis = axis
        self.last_atten = float(header.get("atten_db", self.last_atten))
        t = header.get("t")
        if t is not None and self._last_t is not None and t > self._last_t:
            dt = t - self._last_t
            self.sweep_period_s = dt if self.sweep_period_s == 0.0 else 0.8 * self.sweep_period_s + 0.2 * dt
        self._last_t = t
        self._frames += 1
        if self.client.connected and not self.status_conn.text().startswith("connected"):
            self._set_conn(f"connected to {self.host_edit.text().strip() or '127.0.0.1'} (receiving)")
        mode = self.trace_a.mode
        fresh = self.trace_a.data is None or axis != self.trace_a.axis_key
        self.trace_a.update(axis, p)
        if mode != "view":                  # a frozen trace keeps the flags it was drawn with
            if flags is None:
                self.flags_a = None
            elif mode in ("max_hold", "min_hold", "average") and not fresh and self.flags_a is not None \
                    and self.flags_a.size == flags.size:
                self.flags_a = self.flags_a | flags      # a point that was bad in any sweep stays marked
            else:
                self.flags_a = np.array(flags, dtype=np.uint8)
        data = self.trace_a.data
        if self.track_chk.isChecked() and self.m[0].enabled and data is not None:
            self.m[0].place(axis, core.peak_index(data))
        if self.settings.auto_atten:
            _quiet(self.att_sb, self.last_atten)
        if self._single:
            self._single = False
            self._stop()
        self._redraw()

    def _display_axis(self) -> core.Axis:
        if self.axis is not None:
            return self.axis
        s = self.settings
        return core.Axis(s.start_hz, s.span_hz / max(s.points - 1, 1), s.points)

    def _redraw(self) -> None:
        s, axis = self.settings, self._display_axis()
        data = self.trace_a.data if self.axis is not None else None
        self.view.set_scale(axis.start_hz, axis.stop_hz, s.ref_dbm, s.db_per_div)
        f = axis.freqs()
        self.view.set_trace("a", f, data)
        flags = self.flags_a if (data is not None and self.flags_a is not None and self.flags_a.size == data.size) else None
        self.view.set_bad(f, data, None if flags is None else (flags & FLAGS_UNRELIABLE) != 0)
        if self.trace_b is not None and self.show_b_chk.isChecked() and self.trace_b[0] == axis:
            self.view.set_trace("b", f, self.trace_b[1])
        else:
            self.view.set_trace("b", f, None)

        readout, levels = [], {}
        for n in range(2):
            i = self.m[n].index_in(axis) if (data is not None and self.axis is not None) else None
            if i is None:
                self.view.set_marker(n, None, None, s.ref_dbm, s.db_per_div)
                continue
            levels[n] = (axis.freq_at(i), float(data[i]))
            self.view.set_marker(n, levels[n][0], levels[n][1], s.ref_dbm, s.db_per_div)
            line = core.marker_text(f"M{n + 1}", *levels[n])
            if flags is not None and flags[i]:
                line += "   [" + ", ".join(flag_names(int(flags[i]))) + "]"
            readout.append(line)
        if 0 in levels and 1 in levels:
            readout.append(core.delta_text(*levels[0], *levels[1]))
        self.readout.setText("\n".join(readout))

        att = f"{self.last_atten:g} dB" + (" (auto)" if s.auto_atten else "")
        state = "" if self._remote_running else "   STOPPED"
        self.info.setText(
            f"REF {s.ref_dbm:g} dBm   ATT {att}   RBW {core.format_hz(self.rbw_hz, 0)}   "
            f"{s.db_per_div:g} dB/div   {axis.n} pts   SWP {self.sweep_period_s * 1e3:.0f} ms{state}"
        )
        self.lbl_start.setText(f"Start {core.format_hz(axis.start_hz)}")
        self.lbl_center.setText(f"Center {core.format_hz(axis.center_hz)}   Span {core.format_hz(axis.span_hz)}")
        self.lbl_stop.setText(f"Stop {core.format_hz(axis.stop_hz)}")
        if core.undersampled(s.points, s.span_hz, self.rbw_hz):
            need = core.recommended_points(s.span_hz, self.rbw_hz, self.limits.max_points)
            self.status_warn.setText(f"Step > RBW/2: narrow signals read low. Use about {need} points.")
        else:
            self.status_warn.setText("")

    # ------------------------------------------------------------ connection and simulator

    def _toggle_connect(self) -> None:
        if self.client.connected:
            self.pins.shutdown()
            self.client.disconnect()
            self.synced = False
            self.connect_btn.setText("Connect")
            self._set_conn("not connected")
            self._dev_note(logging.INFO, "disconnected")
            return
        self._connect()

    def _connect(self) -> None:
        self.client.connect(self.host_edit.text().strip() or "127.0.0.1", self.pub_sb.value(), self.rep_sb.value())
        self.connect_btn.setText("Disconnect")
        self._set_conn("connecting…")
        self.synced = False
        self._sync_tries = 0
        self.dev_log.gap = True                 # fetch what sweepd said before we came
        self._log_fetch_tries = 0
        self._dev_note(logging.INFO, f"connecting to {self.host_edit.text().strip() or '127.0.0.1'}")
        self._try_sync()

    def _try_sync(self) -> None:
        if not self.client.connected:
            return
        if self._sync_from_server(timeout_ms=150):
            self._set_conn(f"connected to {self.host_edit.text().strip() or '127.0.0.1'}")
            return
        self._sync_tries += 1
        if self._sync_tries < 20:
            QtCore.QTimer.singleShot(300, self._try_sync)
        else:
            self._set_conn("socket open, but sweepd does not answer on the command port")
            self._dev_note(logging.WARNING, "sweepd does not answer on the command port")

    def start_sim(self) -> None:
        tones = []
        for r in range(self.tones.rowCount()):
            on = self.tones.item(r, 0).checkState() == QtCore.Qt.CheckState.Checked
            try:
                f = float(self.tones.item(r, 1).text())
                p = float(self.tones.item(r, 2).text())
            except (AttributeError, ValueError):
                continue
            if on:
                tones.append((f * 1e6, p))
        try:
            self.runner.start(
                self.pub_sb.value(), self.rep_sb.value(), self.period_sb.value(), tones,
                self.noise_sb.value(), self.sim_rbw_sb.value() * 1e3,
            )
        except (OSError, RuntimeError) as exc:
            self._msg(f"Could not start the simulator: {exc}", warn=True)
            return
        self._sim_exit_reported = False
        self._sim_user_stopped = False
        self.rbw_sb.setValue(self.sim_rbw_sb.value())      # the display RBW follows the simulated filter
        self.sim_btn.setText("Stop simulated hardware")
        self._update_sim_status()
        if self.autoconnect_chk.isChecked():
            if self.client.connected:
                self.pins.shutdown()
                self.client.disconnect()
            self.host_edit.setText("127.0.0.1")
            self._connect()

    def _toggle_sim(self) -> None:
        if self.runner.running:
            self.pins.shutdown()
            self.runner.stop()
            self._sim_exit_reported = True
            self._sim_user_stopped = True
            self.sim_btn.setText("Start simulated hardware")
            self._update_sim_status()
        else:
            self.start_sim()

    def _update_sim_status(self) -> None:
        if self.runner.running:
            self.sim_label.setText(f"running (pid {self.runner.pid})")
        elif self.runner.returncode is not None and not self._sim_user_stopped:
            self.sim_label.setText(f"exited with code {self.runner.returncode}")
            self.sim_btn.setText("Start simulated hardware")
            if not self._sim_exit_reported:
                self._sim_exit_reported = True
                self._msg("Simulated hardware stopped by itself, see the log in the Advanced tab", warn=True)
        else:
            self.sim_label.setText("stopped")
        lines = self.runner.drain_log()
        if len(lines) != self._log_len:
            self._log_len = len(lines)
            self.log_view.setPlainText("\n".join(lines))
            bar = self.log_view.verticalScrollBar()
            bar.setValue(bar.maximum())

    # ------------------------------------------------------------ files

    def _save_csv(self) -> None:
        if self.axis is None or self.trace_a.data is None:
            self._msg("No trace to save yet", warn=True)
            return
        default = str(Path("captures") / time.strftime("trace-%Y%m%d-%H%M%S.csv"))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save trace", default, "CSV (*.csv)")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(core.trace_to_csv(self.axis, self.trace_a.data, self.last_atten))
            self._msg(f"Saved {path}")

    def _save_png(self) -> None:
        default = str(Path("captures") / time.strftime("screen-%Y%m%d-%H%M%S.png"))
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save screenshot", default, "PNG (*.png)")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self.grab().save(path)
            self._msg(f"Saved {path}")

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.pins.shutdown()
        if self.runner.running:
            self.runner.stop()
        self.client.disconnect()
        super().closeEvent(event)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--pub-port", type=int, default=5556)
    ap.add_argument("--rep-port", type=int, default=5557)
    ap.add_argument("--connect", action="store_true", help="connect to sweepd at start")
    ap.add_argument("--sim", action="store_true", help="start simulated hardware at start and connect to it")
    args = ap.parse_args(argv)

    app = pg.mkQApp("SAdiy")
    win = MainWindow(args.host, args.pub_port, args.rep_port)
    win.show()
    if args.sim:
        QtCore.QTimer.singleShot(0, win.start_sim)
    elif args.connect:
        QtCore.QTimer.singleShot(0, win._connect)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
