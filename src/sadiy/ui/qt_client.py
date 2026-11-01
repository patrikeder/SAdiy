"""PyQtGraph client (local on RPi, or remote for the BBB). Untested skeleton.

Needs the `ui` extra:  pip install -e .[ui]
"""
from __future__ import annotations

import argparse

import numpy as np
import pyqtgraph as pg
import zmq
from pyqtgraph.Qt import QtCore, QtWidgets

from ..server import protocol


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--pub-port", type=int, default=5556)
    args = ap.parse_args(argv)

    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{args.host}:{args.pub_port}")
    sub.setsockopt(zmq.SUBSCRIBE, protocol.TOPIC)

    app = QtWidgets.QApplication([])
    win = pg.PlotWidget(title="SAdiy")
    win.setLabel("bottom", "Frequency", units="Hz")
    win.setLabel("left", "Level", units="dBm")
    win.showGrid(x=True, y=True)
    curve = win.plot(pen="y")
    peak = win.plot(pen="r")
    peak_hold = {"p": None}
    win.show()

    def poll() -> None:
        latest = None
        while sub.poll(0):  # drain, keep only the newest frame
            latest = sub.recv_multipart()
        if latest is None:
            return
        header, p = protocol.decode_frame(latest)
        f = header["f_start_hz"] + np.arange(header["n"]) * header["f_step_hz"]
        curve.setData(f, p)
        ph = peak_hold["p"]
        peak_hold["p"] = p.copy() if ph is None or ph.size != p.size else np.maximum(ph, p)
        peak.setData(f, peak_hold["p"])

    timer = QtCore.QTimer()
    timer.timeout.connect(poll)
    timer.start(30)
    app.exec()


if __name__ == "__main__":
    main()
