"""The Pins tab: clickable BBB board, pin control, raw board access, check patterns.

Thin Qt layer over `bench_core.py`. It talks to `sweepd` through the same REQ socket as the rest of the
GUI, so it works against a remote BBB and against the fake backend of `sweepd --sim`.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, List, Optional

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from .. import patterns, pinmap
from . import bench_core as core

C_BOARD = "#17331f"
C_BLOCK = "#f8f9fa"
C_HIGH = "#ffd43b"
C_LOW = "#343a40"
C_UNKNOWN = "#ced4da"
C_SELECT = "#ff2020"
POLL_MS = 300


def _mono() -> QtGui.QFont:
    return QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)


def _button(text: str, slot, tip: str = "") -> QtWidgets.QPushButton:
    b = QtWidgets.QPushButton(text)
    b.clicked.connect(lambda _checked=False: slot())
    if tip:
        b.setToolTip(tip)
    return b


def _group(title: str, layout: QtWidgets.QLayout) -> QtWidgets.QGroupBox:
    box = QtWidgets.QGroupBox(title)
    box.setLayout(layout)
    return box


class BoardCanvas(QtWidgets.QWidget):
    """Draws the BBB headers and the three boards in canvas units, scaled to the widget."""

    def __init__(self, on_select: Callable[[str], None]) -> None:
        super().__init__()
        self.on_select = on_select
        self.level_of: Callable[[str], tuple] = lambda _pid: (None, None)
        self.selected: Optional[str] = None
        self.expert = False
        self._blocks = core.blocks()
        self._wires = core.wires()
        self.setMinimumSize(620, 430)
        self.setMouseTracking(True)

    def _scale(self):
        s = min(self.width() / core.CANVAS_W, self.height() / core.CANVAS_H)
        return s, (self.width() - core.CANVAS_W * s) / 2, (self.height() - core.CANVAS_H * s) / 2

    def to_canvas(self, pos: QtCore.QPoint):
        s, ox, oy = self._scale()
        return (pos.x() - ox) / s, (pos.y() - oy) / s

    def to_widget(self, x: float, y: float) -> QtCore.QPoint:
        s, ox, oy = self._scale()
        return QtCore.QPoint(int(x * s + ox), int(y * s + oy))

    def mousePressEvent(self, event) -> None:
        pid = core.hit_test(*self.to_canvas(event.pos()))
        if pid is not None:
            self.on_select(pid)

    def mouseMoveEvent(self, event) -> None:
        pid = core.hit_test(*self.to_canvas(event.pos()))
        if pid is None:
            self.setToolTip("")
        else:
            pin = pinmap.PINS[pid]
            self.setToolTip(f"{pid} {pin.name}" + (f" = {pin.net}" if pin.net else ""))

    def paintEvent(self, _event) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        s, ox, oy = self._scale()
        p.translate(ox, oy)
        p.scale(s, s)
        small = QtGui.QFont(self.font())
        small.setPixelSize(10)
        bold = QtGui.QFont(small)
        bold.setBold(True)
        p.setFont(small)
        self._draw_bbb(p, small, bold)
        self._draw_wires(p)
        self._draw_pins(p, small, bold)
        self._draw_blocks(p, small, bold)
        self._draw_legend(p, small)
        p.end()

    def _draw_bbb(self, p, small, bold) -> None:
        top, height = 8.0, core.HEADER_TOP + core.ROWS * core.ROW_H - 2
        p.setPen(QtGui.QPen(QtGui.QColor("#0b1f12"), 2))
        p.setBrush(QtGui.QColor(C_BOARD))
        p.drawRoundedRect(QtCore.QRectF(212, top, 410, height), 8, 8)
        p.setPen(QtGui.QColor("#ffffff"))
        p.setFont(bold)
        p.drawText(QtCore.QRectF(212, top + 2, 410, 16), QtCore.Qt.AlignHCenter, "BeagleBone Black")
        for title, x in (("P8", 280.0), ("P9", 470.0)):
            p.drawText(QtCore.QRectF(x, top + 22, 2 * core.PIN_W + 3, 16), QtCore.Qt.AlignHCenter, title)
        p.setFont(small)

    def _draw_wires(self, p) -> None:
        for wire in self._wires:
            pin = pinmap.PINS[wire.pin_id]
            level, _direction = self.level_of(wire.pin_id)
            width = 2.6 if wire.pin_id == self.selected else 1.5
            colour = QtGui.QColor(core.CATEGORY_COLOURS[pin.category])
            if level == 1:
                colour = colour.lighter(135)
            pen = QtGui.QPen(colour, width)
            if pin.category == "gnd":
                pen.setStyle(QtCore.Qt.DashLine)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            (x0, y0), (x1, y1), (x2, y2) = wire.points
            path = QtGui.QPainterPath(QtCore.QPointF(x0, y0))
            path.lineTo(x1, y1)
            xm = (x1 + x2) / 2
            path.cubicTo(xm, y1, xm, y2, x2, y2)
            p.drawPath(path)

    def _draw_pins(self, p, small, bold) -> None:
        for pin in pinmap.PINS.values():
            x, y, w, h = core.pin_rect(pin)
            rect = QtCore.QRectF(x, y, w, h)
            fill = QtGui.QColor(core.CATEGORY_COLOURS[pin.category])
            locked = pin.access == pinmap.DISPLAY or (pin.access == pinmap.EXPERT and not self.expert)
            if pin.id == self.selected:
                p.setPen(QtGui.QPen(QtGui.QColor(C_SELECT), 2.4))
            else:
                p.setPen(QtGui.QPen(QtGui.QColor("#0b1f12"), 1))
            p.setBrush(fill)
            p.drawRoundedRect(rect, 3, 3)
            light = fill.lightness() > 150
            p.setPen(QtGui.QColor("#212529" if light else "#ffffff"))
            p.setFont(bold if pin.net else small)
            p.drawText(rect.adjusted(0, 0, -5, 0), QtCore.Qt.AlignCenter, str(pin.number))
            level, _direction = self.level_of(pin.id)
            if level is not None:
                p.setPen(QtGui.QPen(QtGui.QColor("#000000"), 0.6))
                p.setBrush(QtGui.QColor(C_HIGH if level else C_LOW))
                p.drawEllipse(QtCore.QPointF(x + w - 5, y + h / 2), 3.2, 3.2)
            # the label next to the pin
            p.setFont(small)
            p.setPen(QtGui.QColor("#ffffff" if pin.net else "#86a890" if locked else "#b8d4bf"))
            odd = pin.number % 2 == 1
            box = QtCore.QRectF(x - 66, y, 63, h) if odd else QtCore.QRectF(x + w + 3, y, 63, h)
            align = (QtCore.Qt.AlignRight if odd else QtCore.Qt.AlignLeft) | QtCore.Qt.AlignVCenter
            p.drawText(box, align, pin.short)

    def _draw_blocks(self, p, small, bold) -> None:
        for block in self._blocks:
            x, y, w, h = block.rect
            p.setPen(QtGui.QPen(QtGui.QColor("#343a40"), 1.5))
            p.setBrush(QtGui.QColor(C_BLOCK))
            p.drawRoundedRect(QtCore.QRectF(x, y, w, h), 6, 6)
            p.setPen(QtGui.QColor("#212529"))
            p.setFont(bold)
            p.drawText(QtCore.QRectF(x + 8, y + 4, w - 16, 16), QtCore.Qt.AlignLeft, block.board.title)
            p.setFont(small)
            p.setPen(QtGui.QColor("#6c757d"))
            p.drawText(QtCore.QRectF(x + 8, y + 20, w - 16, 16), QtCore.Qt.AlignLeft, block.board.subtitle)
            for row in block.rows:
                self._draw_row(p, row, small, bold)
            sy = y + core._BLOCK_HEAD + len(block.rows) * core._BLOCK_ROW_H + 4
            p.setFont(small)
            p.setPen(QtGui.QColor("#6c757d"))
            for strap in block.board.straps:
                p.drawText(QtCore.QRectF(x + 8, sy, w - 12, core._STRAP_H), QtCore.Qt.AlignLeft, strap)
                sy += core._STRAP_H

    def _draw_row(self, p, row: core.BlockRow, small, bold) -> None:
        x, y, w, h = row.rect
        pin = pinmap.PINS[row.pin_id]
        if row.pin_id == self.selected:
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(QtGui.QColor("#ffe3e3"))
            p.drawRect(QtCore.QRectF(x, y, w, h))
        level, direction = self.level_of(row.pin_id)
        p.setPen(QtGui.QPen(QtGui.QColor("#212529"), 0.8))
        p.setBrush(QtGui.QColor(C_UNKNOWN if level is None else C_HIGH if level else C_LOW))
        p.drawEllipse(QtCore.QPointF(x + 11, y + h / 2), 5, 5)
        p.setPen(QtGui.QColor("#212529"))
        p.setFont(bold)
        p.drawText(QtCore.QRectF(x + 21, y, w - 21, h), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft,
                   pin.board_pin.split(" via")[0])
        p.setFont(small)
        p.setPen(QtGui.QColor("#495057"))
        text = f"{row.pin_id}  {direction or ''}"
        p.drawText(QtCore.QRectF(x + 21, y, w - 27, h), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignRight, text)

    def _draw_legend(self, p, small) -> None:
        p.setFont(small)
        x, y = 8.0, core.CANVAS_H - 34
        for key, label in core.CATEGORY_LABELS:
            width = 16 + QtGui.QFontMetricsF(small).horizontalAdvance(label) + 12
            if x + width > core.CANVAS_W - 4:
                x, y = 8.0, y + 16
            p.setPen(QtGui.QPen(QtGui.QColor("#343a40"), 0.6))
            p.setBrush(QtGui.QColor(core.CATEGORY_COLOURS[key]))
            p.drawRect(QtCore.QRectF(x, y + 2, 11, 11))
            p.setPen(self.palette().color(QtGui.QPalette.WindowText))
            p.drawText(QtCore.QRectF(x + 15, y, width, 15), QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, label)
            x += width


class PinsTab(QtWidgets.QWidget):
    def __init__(self, request, stop_sweep: Callable[[], None], message: Callable[..., None],
                 weights_db=patterns.DEFAULT_WEIGHTS_DB, active_high: bool = True) -> None:
        super().__init__()
        self._stop_sweep = stop_sweep
        self._message = message
        self.ask_user: Callable[[str], bool] = self._ask_dialog
        self.session = core.BenchSession(request, lambda text: self.ask_user(text), weights_db, active_high)
        self.selected: Optional[str] = None
        self.pattern: Optional[patterns.Pattern] = None

        self.canvas = BoardCanvas(self.select_pin)
        self.canvas.level_of = self.session.level

        self.mode_btn = _button("Enter bench mode", self.toggle_mode, "Stops sweeping and takes over the pins")
        self.mode_label = QtWidgets.QLabel("Bench mode off. Connect to sweepd, then enter bench mode.")
        self.mode_label.setWordWrap(True)
        self.expert_chk = QtWidgets.QCheckBox("Expert: unlock free GPIO")
        self.expert_chk.setToolTip("Allows pins that are not in the pin map. Check first that nothing else uses them.")
        self.expert_chk.toggled.connect(self._on_expert)
        top = QtWidgets.QHBoxLayout()
        top.addWidget(self.mode_btn)
        top.addWidget(self.expert_chk)
        top.addWidget(self.mode_label, 1)

        self.side = QtWidgets.QTabWidget()
        self.side.addTab(self._build_pin_page(), "Pin")
        self.side.addTab(self._scrolled(self._build_raw_page()), "Raw access")
        self.side.addTab(self._scrolled(self._build_pattern_page()), "Patterns")
        self.side.setFixedWidth(475)

        body = QtWidgets.QHBoxLayout()
        body.addWidget(self.canvas, 1)
        body.addWidget(self.side)
        col = QtWidgets.QVBoxLayout(self)
        col.addLayout(top)
        col.addLayout(body, 1)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self._set_active_ui()
        self.select_pin(pinmap.BY_NET["ATT_V1"].id)

    @staticmethod
    def _scrolled(page: QtWidgets.QWidget) -> QtWidgets.QScrollArea:
        area = QtWidgets.QScrollArea()
        area.setWidget(page)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        return area

    def _ask_dialog(self, text: str) -> bool:
        answer = QtWidgets.QMessageBox.question(self, "Confirm", text + "\n\nGo ahead?")
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    # ------------------------------------------------------------ pages
    def _build_pin_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(page)
        self.pin_info = QtWidgets.QLabel()
        self.pin_info.setWordWrap(True)
        self.pin_info.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        col.addWidget(self.pin_info)
        self.pin_level = QtWidgets.QLabel("Level: -")
        self.pin_level.setFont(_mono())
        col.addWidget(self.pin_level)
        row = QtWidgets.QGridLayout()
        self.drive0_btn = _button("Drive 0", lambda: self.drive(0))
        self.drive1_btn = _button("Drive 1", lambda: self.drive(1))
        self.input_btn = _button("Input (stop driving)", self.release)
        self.read_btn = _button("Read", self.read_pin)
        self.bus_btn = _button("Back to bus", self.to_bus, "Give the pin back to the SPI or I2C controller")
        row.addWidget(self.drive0_btn, 0, 0)
        row.addWidget(self.drive1_btn, 0, 1)
        row.addWidget(self.input_btn, 1, 0)
        row.addWidget(self.read_btn, 1, 1)
        row.addWidget(self.bus_btn, 2, 0, 1, 2)
        col.addLayout(row)
        col.addStretch(1)
        return page

    def _build_raw_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(page)

        # ADF4351
        self.word_edit = QtWidgets.QLineEdit("0x00580005")
        self.word_edit.setMinimumWidth(80)
        self.init_edits: List[QtWidgets.QLineEdit] = []
        g = QtWidgets.QGridLayout()
        g.addWidget(QtWidgets.QLabel("Hex"), 0, 0)
        g.addWidget(self.word_edit, 0, 1)
        g.addWidget(_button("Send", self.send_word), 0, 2)
        for i, reg in enumerate(core.INIT_ORDER):
            edit = QtWidgets.QLineEdit()
            edit.setPlaceholderText("from ADI's software")
            edit.setMinimumWidth(80)
            self.init_edits.append(edit)
            g.addWidget(QtWidgets.QLabel(f"R{reg}"), 1 + i, 0)
            g.addWidget(edit, 1 + i, 1)
            g.addWidget(_button("Send", lambda n=i: self.send_init_register(n)), 1 + i, 2)
        g.addWidget(_button("Send R5..R0 in order", self.send_init), 7, 0, 1, 3)
        self.ld_label = QtWidgets.QLabel("LD: -")
        self.rf_main_chk = QtWidgets.QCheckBox("Main (RFOUTA)")
        self.rf_aux_chk = QtWidgets.QCheckBox("Aux (RFOUTB)")
        self.rf_power_cb = QtWidgets.QComboBox()
        for dbm in (-4, -1, 2, 5):
            self.rf_power_cb.addItem(f"{dbm:+d} dBm", dbm)
        g.addWidget(self.ld_label, 8, 0)
        g.addWidget(_button("Read LD", self.read_ld), 8, 1, 1, 2)
        g.addWidget(self.rf_main_chk, 9, 0, 1, 2)
        g.addWidget(self.rf_power_cb, 9, 2)
        g.addWidget(self.rf_aux_chk, 10, 0, 1, 2)
        g.addWidget(_button("Apply", self.apply_rf, "RF outputs turn on only when the PLL is locked"), 10, 2)
        self.raw_note = QtWidgets.QLabel("RF outputs stay off until locked and applied here. The R4 box must not enable them.")
        self.raw_note.setWordWrap(True)
        g.addWidget(self.raw_note, 11, 0, 1, 3)
        col.addWidget(_group("ADF4351", g))

        # PE4302
        self.v_checks: List[QtWidgets.QCheckBox] = []
        g = QtWidgets.QGridLayout()
        for i in range(6):
            chk = QtWidgets.QCheckBox(f"V{i + 1}")
            chk.setChecked(True)
            self.v_checks.append(chk)
            g.addWidget(chk, 0, i)
        self.raw_order_chk = QtWidgets.QCheckBox("Raw, no ordering (wiring test)")
        self.raw_order_chk.setToolTip("Writes V1 to V6 in that order. Attenuation can dip during the change.")
        g.addWidget(self.raw_order_chk, 1, 0, 1, 6)
        g.addWidget(_button("Apply V1..V6", self.apply_levels), 2, 0, 1, 3)
        g.addWidget(_button("Max (31.5 dB)", lambda: self.set_db(31.5)), 2, 3, 1, 3)
        self.db_sb = QtWidgets.QDoubleSpinBox()
        self.db_sb.setRange(0, 31.5)
        self.db_sb.setSingleStep(0.5)
        self.db_sb.setSuffix(" dB")
        self.db_sb.setValue(31.5)
        g.addWidget(self.db_sb, 3, 0, 1, 3)
        g.addWidget(_button("Set dB", lambda: self.set_db(self.db_sb.value())), 3, 3, 1, 3)
        self.att_label = QtWidgets.QLabel("Attenuation: -")
        self.att_label.setWordWrap(True)
        g.addWidget(self.att_label, 4, 0, 1, 6)
        self.writes_label = QtWidgets.QLabel("Writes: -")
        self.writes_label.setFont(_mono())
        self.writes_label.setWordWrap(True)
        g.addWidget(self.writes_label, 5, 0, 1, 6)
        col.addWidget(_group("PE4302", g))

        # ADCs: the ADS1115 is the main one on every platform, AIN0 the cross-check on the BBB
        g = QtWidgets.QGridLayout()
        self.ads_ch_cb = QtWidgets.QComboBox()
        self.ads_ch_cb.addItems([f"A{i}" for i in range(4)])
        self.ads_ch_cb.setMinimumWidth(60)
        g.addWidget(QtWidgets.QLabel("ADS1115"), 0, 0)
        g.addWidget(self.ads_ch_cb, 0, 1)
        g.addWidget(_button("Convert", self.read_ads), 0, 2)
        g.addWidget(_button("Read regs", self.read_ads_regs), 0, 3)
        self.ads_label = QtWidgets.QLabel("-")
        self.ads_label.setFont(_mono())
        self.ads_label.setWordWrap(True)
        g.addWidget(self.ads_label, 1, 0, 1, 4)
        self.ain_n_sb = QtWidgets.QSpinBox()
        self.ain_n_sb.setRange(1, 256)
        self.ain_n_sb.setPrefix("mean of ")
        g.addWidget(QtWidgets.QLabel("AIN0 (check)"), 2, 0)
        g.addWidget(self.ain_n_sb, 2, 1)
        g.addWidget(_button("Read", self.read_ain), 2, 2, 1, 2)
        self.ain_label = QtWidgets.QLabel("-")
        self.ain_label.setFont(_mono())
        self.ain_label.setWordWrap(True)
        g.addWidget(self.ain_label, 3, 0, 1, 4)
        col.addWidget(_group("ADC", g))
        col.addStretch(1)
        return page

    def _build_pattern_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        col = QtWidgets.QVBoxLayout(page)
        self.kind_cb = QtWidgets.QComboBox()
        for label, key in (
            ("Walking one", "walking1"), ("Walking zero", "walking0"), ("Square wave (one pin)", "square"),
            ("Binary counter", "counter"), ("PE4302 stages: one out, others in", "stages_out"),
            ("PE4302 stages: one in, others out", "stages_in"), ("ADF4351 frame repeated", "frame"),
        ):
            self.kind_cb.addItem(label, key)
        self.kind_cb.currentIndexChanged.connect(lambda _i: self.refresh_preview())
        self.pin_list = QtWidgets.QListWidget()
        self.pin_list.setMaximumHeight(150)
        self.pin_list.itemChanged.connect(lambda _item: self.refresh_preview())
        self.cycles_sb = QtWidgets.QSpinBox()
        self.cycles_sb.setRange(1, 10000)
        self.cycles_sb.valueChanged.connect(lambda _v: self.refresh_preview())
        self.rate_sb = QtWidgets.QDoubleSpinBox()
        self.rate_sb.setRange(0.1, 100000)
        self.rate_sb.setDecimals(1)
        self.rate_sb.setValue(10.0)
        self.rate_sb.setSuffix(" steps/s")
        self.rate_sb.valueChanged.connect(lambda _v: self.refresh_preview())
        self.loop_chk = QtWidgets.QCheckBox("Loop until stopped")
        self.loop_chk.toggled.connect(lambda _c: self.refresh_preview())
        self.frame_edit = QtWidgets.QLineEdit("0x00580005")
        self.frame_edit.setToolTip("Hex words separated by spaces. Words that enable an RF output are refused.")
        self.frame_edit.textChanged.connect(lambda _t: self.refresh_preview())
        g = QtWidgets.QGridLayout()
        g.addWidget(self.kind_cb, 0, 0, 1, 2)
        g.addWidget(self.pin_list, 1, 0, 1, 2)
        g.addWidget(QtWidgets.QLabel("Cycles / repeats"), 2, 0)
        g.addWidget(self.cycles_sb, 2, 1)
        g.addWidget(QtWidgets.QLabel("Rate"), 3, 0)
        g.addWidget(self.rate_sb, 3, 1)
        g.addWidget(QtWidgets.QLabel("SPI words"), 4, 0)
        g.addWidget(self.frame_edit, 4, 1)
        g.addWidget(self.loop_chk, 5, 0, 1, 2)
        col.addLayout(g)
        row = QtWidgets.QHBoxLayout()
        self.run_btn = _button("Run", self.run_pattern)
        self.stop_btn = _button("Stop", self.stop_pattern)
        row.addWidget(self.run_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(_button("Export CSV…", self.export_csv, "For comparison with a DSLogic capture"))
        col.addLayout(row)
        self.run_label = QtWidgets.QLabel("Not running")
        self.run_label.setWordWrap(True)
        col.addWidget(self.run_label)
        self.preview = QtWidgets.QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setFont(_mono())
        self.preview.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.preview.setMinimumHeight(180)
        col.addWidget(self.preview, 1)
        self._fill_pin_list()
        return page

    def _fill_pin_list(self) -> None:
        checked = set(self.checked_pins())
        self.pin_list.blockSignals(True)
        self.pin_list.clear()
        for pin in pinmap.PINS.values():
            if pin.access == pinmap.WIRED or (pin.access == pinmap.EXPERT and self.expert_chk.isChecked()):
                label = f"{pin.id}  {pin.net}" if pin.net else f"{pin.id}  {pin.name}  (expert)"
                item = QtWidgets.QListWidgetItem(label)
                item.setData(QtCore.Qt.UserRole, pin.signal)
                item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled)
                on = pin.signal in checked or (not checked and pin.net in pinmap.ATT_NETS)
                item.setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
                self.pin_list.addItem(item)
        self.pin_list.blockSignals(False)

    def checked_pins(self) -> List[str]:
        return [
            self.pin_list.item(i).data(QtCore.Qt.UserRole) for i in range(self.pin_list.count())
            if self.pin_list.item(i).checkState() == QtCore.Qt.Checked
        ]

    # ------------------------------------------------------------ mode
    def _show(self, reply: dict, ok_text: str = "") -> bool:
        if reply.get("ok"):
            if ok_text:
                self._message(ok_text)
            return True
        if not reply.get("cancelled"):
            self._message(reply.get("error", "refused"), warn=True)
        return False

    def toggle_mode(self) -> None:
        if self.session.active:
            self.leave()
        else:
            self.enter()

    def enter(self) -> None:
        reply = self.session.open(self._agree_stop_sweep)
        if self._show(reply, "Bench mode on"):
            self.timer.start(POLL_MS)
        self._set_active_ui()
        if self.session.warnings:
            self._message("; ".join(self.session.warnings), warn=True)
        self.refresh_preview()
        self.canvas.update()

    def _agree_stop_sweep(self) -> bool:
        if not self.ask_user("A sweep is running. Bench mode and sweeping exclude each other. Stop the sweep?"):
            return False
        self._stop_sweep()
        return True

    def leave(self) -> None:
        """Back to the safe state: the daemon does it on bench_close."""
        self.timer.stop()
        reply = self.session.close()
        self._show(reply, "Bench mode off, lines in the safe state. Press Run to sweep again.")
        self._set_active_ui()
        self.canvas.update()

    def shutdown(self) -> None:
        """The connection is going away."""
        self.timer.stop()
        self.session.close()
        self._set_active_ui()

    def poll(self) -> None:
        if not self.session.active:
            return
        reply = self.session.poll()
        if reply.get("closed"):
            self.timer.stop()
            self._message(reply["error"], warn=True)
            self._set_active_ui()
        elif reply.get("ok"):
            self._update_live(reply)
        self.canvas.update()

    def _update_live(self, status: dict) -> None:
        self._update_pin_level()
        ld = status.get("ld")
        self.ld_label.setText(f"LD: {'-' if ld is None else ld}")
        att = status.get("attenuation_db")
        if att is not None:
            self.att_label.setText(f"Attenuation: {att:g} dB")
        for chk, pid in zip(self.v_checks, (pinmap.BY_NET[n].id for n in pinmap.ATT_NETS)):
            level = self.session.level(pid)[0]
            if level is not None and not chk.underMouse():
                chk.blockSignals(True)
                chk.setChecked(bool(level))
                chk.blockSignals(False)
        run = status.get("pattern")
        if run:
            if run.get("running"):
                self.run_label.setText(
                    f"Running: {run['name']}, step {run['step']} of {run['total']}, loop {run['loops']}. "
                    f"Asked {run['rate_hz']:g} steps/s, measured {run['measured_hz']:.0f} steps/s")
            elif run.get("error"):
                self.run_label.setText(f"{run['name']}: {run['error']}")
            else:
                self.run_label.setText(
                    f"{run['end'].capitalize()}: {run['name']}, {run['steps']} steps. "
                    f"Asked {run['rate_hz']:g} steps/s, measured {run['measured_hz']:.0f} steps/s. Lines back to safe.")
        if status.get("last_error"):
            self._message(status["last_error"], warn=True)
        rf = status.get("rf", {})
        self.raw_note.setText(
            f"RF: main {'ON' if rf.get('main') else 'off'}, aux {'ON' if rf.get('aux') else 'off'}. "
            "Outputs turn on only here, after lock.")

    def _set_active_ui(self) -> None:
        on = self.session.active
        self.mode_btn.setText("Leave bench mode" if on else "Enter bench mode")
        if on:
            limits = self.session.limits or {}
            sim = " SIMULATED, no hardware is touched." if limits.get("simulated") else ""
            self.mode_label.setText(f"Bench mode on: {limits.get('backend', '')}.{sim} Leaving returns all lines to safe.")
            self.mode_label.setStyleSheet("color:#c05000;font-weight:bold;")
        else:
            self.mode_label.setText("Bench mode off. Connect to sweepd, then enter bench mode.")
            self.mode_label.setStyleSheet("")
        self._update_pin_controls()

    def _on_expert(self, checked: bool) -> None:
        self.session.expert = checked
        self.canvas.expert = checked
        self._fill_pin_list()
        self._update_pin_controls()
        self.canvas.update()

    # ------------------------------------------------------------ pin page
    def select_pin(self, pid: str) -> None:
        self.selected = pid
        self.canvas.selected = pid
        self.pin_info.setText(core.describe_pin(pinmap.PINS[pid]))
        self.side.setCurrentIndex(0)
        self._update_pin_controls()
        self._update_pin_level()
        self.canvas.update()

    def _update_pin_controls(self) -> None:
        if self.selected is None:
            return
        pin = pinmap.PINS[self.selected]
        on = self.session.active
        may_use = pin.access == pinmap.WIRED or (pin.access == pinmap.EXPERT and self.expert_chk.isChecked())
        self.drive0_btn.setEnabled(on and may_use)
        self.drive1_btn.setEnabled(on and may_use)
        self.input_btn.setEnabled(on and may_use)
        self.read_btn.setEnabled(on and (may_use or pin.access == pinmap.INPUT_ONLY))
        self.bus_btn.setEnabled(on and pin.mux is not None)

    def _update_pin_level(self) -> None:
        if self.selected is None:
            return
        level, direction = self.session.level(self.selected)
        text = "-" if level is None else str(level)
        self.pin_level.setText(f"Level: {text}   Direction: {direction or '-'}")

    def _after_pin(self, reply: dict) -> None:
        if self._show(reply):
            self._message(f"{reply['pin']}: level {reply['level']}, {reply['dir']}")
        self.poll()

    def drive(self, value: int) -> None:
        self._after_pin(self.session.drive(self.selected, value))

    def release(self) -> None:
        self._after_pin(self.session.release(self.selected))

    def read_pin(self) -> None:
        self._after_pin(self.session.read_pin(self.selected))

    def to_bus(self) -> None:
        self._after_pin(self.session.to_bus(self.selected))

    # ------------------------------------------------------------ raw page
    def _send(self, words: List[int]) -> None:
        reply = self.session.send_words(words)
        if self._show(reply, f"Sent {' '.join(reply.get('sent', ()))}"):
            self.ld_label.setText(f"LD: {reply.get('ld')}")
        self.poll()

    def send_word(self) -> None:
        try:
            self._send([core.parse_word(self.word_edit.text())])
        except ValueError as exc:
            self._message(str(exc), warn=True)

    def send_init_register(self, index: int) -> None:
        reg = core.INIT_ORDER[index]
        try:
            word = core.parse_word(self.init_edits[index].text())
            if word & 7 != reg:
                raise ValueError(f"0x{word:08X} is not an R{reg} word: its address bits are {word & 7}")
            self._send([word])
        except ValueError as exc:
            self._message(str(exc), warn=True)

    def send_init(self) -> None:
        try:
            self._send(core.init_sequence([e.text() for e in self.init_edits]))
        except ValueError as exc:
            self._message(str(exc), warn=True)

    def read_ld(self) -> None:
        self.poll()
        ld = self.session.status.get("ld") if self.session.active else None
        self.ld_label.setText(f"LD: {'-' if ld is None else ld}")

    def apply_rf(self) -> None:
        reply = self.session.set_rf(self.rf_main_chk.isChecked(), self.rf_aux_chk.isChecked(), self.rf_power_cb.currentData())
        if not self._show(reply, f"RF outputs: sent {reply.get('sent')}"):
            self.rf_main_chk.setChecked(False)
            self.rf_aux_chk.setChecked(False)
        self.poll()

    def _after_atten(self, reply: dict) -> None:
        if self._show(reply):
            writes = " ".join(f"{name.replace('ATT_', '')}={level}" for name, level in reply.get("writes", ())) or "(none)"
            self.att_label.setText(f"Attenuation: {reply['attenuation_db']:g} dB")
            self.writes_label.setText(f"Writes: {writes}")
        self.poll()

    def apply_levels(self) -> None:
        levels = [1 if c.isChecked() else 0 for c in self.v_checks]
        self._after_atten(self.session.set_levels(levels, self.raw_order_chk.isChecked()))

    def set_db(self, db: float) -> None:
        self._after_atten(self.session.set_db(db))

    def read_ads(self) -> None:
        reply = self.session.read_ads1115(self.ads_ch_cb.currentIndex())
        if self._show(reply):
            self.ads_label.setText(
                f"A{reply['channel']}: code {reply['code']}, {reply['volts']:.4f} V (±{reply['full_scale_v']:g} V)\n"
                f"config 0x{reply['config']:04X}  conversion 0x{reply['conversion']:04X}")

    def read_ads_regs(self) -> None:
        reply = self.session.read_ads1115(self.ads_ch_cb.currentIndex(), single=False)
        if self._show(reply):
            self.ads_label.setText(f"config 0x{reply['config']:04X}  conversion 0x{reply['conversion']:04X}")

    def read_ain(self) -> None:
        reply = self.session.read_ain(0, self.ain_n_sb.value())
        if self._show(reply):
            self.ain_label.setText(
                f"raw {reply['raw']:.1f}, {reply['volts']:.4f} V at the pin, "
                f"{reply['volts_detector']:.4f} V at the detector")

    # ------------------------------------------------------------ pattern page
    def current_spec(self) -> dict:
        key = self.kind_cb.currentData()
        cycles = self.cycles_sb.value()
        if key in ("walking1", "walking0"):
            return {"kind": "walking", "signals": self.checked_pins(), "active": 1 if key == "walking1" else 0, "cycles": cycles}
        if key == "square":
            return {"kind": "square", "signals": self.checked_pins()[:1], "cycles": cycles}
        if key == "counter":
            return {"kind": "counter", "signals": self.checked_pins()}
        if key in ("stages_out", "stages_in"):
            return {"kind": "pe4302_stages", "mode": "one_out" if key == "stages_out" else "one_in"}
        return {"kind": "adf4351_frame", "words": [core.parse_word(t) for t in self.frame_edit.text().split()], "repeat": cycles}

    def refresh_preview(self) -> None:
        try:
            self.pattern = self.session.build_pattern(self.current_spec())
            self.preview.setPlainText(core.preview_text(
                self.pattern, self.rate_sb.value(), self.session.limits, self.loop_chk.isChecked()))
        except ValueError as exc:
            self.pattern = None
            self.preview.setPlainText(str(exc))

    def run_pattern(self) -> None:
        self.refresh_preview()
        if self.pattern is None:
            self._message("Fix the pattern first: see the preview", warn=True)
            return
        reply = self.session.start_pattern(self.current_spec(), self.rate_sb.value(), self.loop_chk.isChecked())
        self._show(reply, "Pattern running")
        self.poll()

    def stop_pattern(self) -> None:
        self._show(self.session.stop_pattern(), "Pattern stopped, lines back to safe")
        self.poll()

    def export_csv(self, path: Optional[str] = None) -> None:
        self.refresh_preview()
        if self.pattern is None:
            self._message("Nothing to export: see the preview", warn=True)
            return
        if path is None:
            default = str(Path("captures") / time.strftime("pattern-%Y%m%d-%H%M%S.csv"))
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export pattern", default, "CSV (*.csv)")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(patterns.to_csv(self.pattern))
            self._message(f"Saved {path}")
