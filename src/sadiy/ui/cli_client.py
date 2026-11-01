"""Terminal client: prints the peak of every sweep. Handy for headless checks over ssh."""
from __future__ import annotations

import argparse

import zmq

from ..server import protocol


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--pub-port", type=int, default=5556)
    ap.add_argument("--count", type=int, default=0, help="stop after N frames (0 = forever)")
    args = ap.parse_args(argv)

    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{args.host}:{args.pub_port}")
    sub.setsockopt(zmq.SUBSCRIBE, protocol.TOPIC)

    n = 0
    while args.count == 0 or n < args.count:
        header, p = protocol.decode_frame(sub.recv_multipart())
        i = int(p.argmax())
        f_peak = header["f_start_hz"] + i * header["f_step_hz"]
        print(
            f"seq {header['seq']:5d}  atten {header['atten_db']:4.1f} dB  "
            f"peak {p[i]:7.2f} dBm @ {f_peak / 1e6:9.3f} MHz"
        )
        n += 1


if __name__ == "__main__":
    main()
