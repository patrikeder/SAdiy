"""Terminal client: prints the peak of every sweep, and with --log-level what sweepd reports.
Handy for headless checks over ssh."""
from __future__ import annotations

import argparse

import zmq

from .. import logs
from ..server import protocol

LEVEL_CHOICES = [name for name in logs.LEVELS if name != "trace"]     # trace never leaves the BBB


def print_history(host: str, rep_port: int, min_level: int, ctx) -> int:
    """What sweepd kept before we connected. Returns the last record number, 0 when there is none."""
    req = ctx.socket(zmq.REQ)
    req.setsockopt(zmq.LINGER, 0)
    req.connect(f"tcp://{host}:{rep_port}")
    try:
        req.send_json({"cmd": "log", "level": "debug", "limit": 50})
        if not req.poll(1000):
            print("(sweepd does not answer on the command port: no log history)")
            return 0
        reply = req.recv_json()
    finally:
        req.close(linger=0)
    if not reply.get("ok"):
        print(f"(sweepd has no log: {reply.get('error')})")
        return 0
    for d in reply["entries"]:
        e = logs.LogEntry.from_dict(d)
        if e.level >= min_level:
            print(logs.format_entry(e, with_date=True))
    return int(reply["last_seq"])


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--pub-port", type=int, default=5556)
    ap.add_argument("--rep-port", type=int, default=5557)
    ap.add_argument("--count", type=int, default=0, help="stop after N frames (0 = forever)")
    ap.add_argument("--log-level", choices=LEVEL_CHOICES,
                    help="also print sweepd's log from this level up: first what it kept, then live")
    args = ap.parse_args(argv)

    ctx = zmq.Context()
    sub = ctx.socket(zmq.SUB)
    sub.connect(f"tcp://{args.host}:{args.pub_port}")
    sub.setsockopt(zmq.SUBSCRIBE, protocol.TOPIC)
    min_level = None
    last_seq = 0
    if args.log_level:
        min_level = logs.parse_level(args.log_level)
        sub.setsockopt(zmq.SUBSCRIBE, protocol.LOG_TOPIC)
        last_seq = print_history(args.host, args.rep_port, min_level, ctx)

    n = 0
    while args.count == 0 or n < args.count:
        parts = sub.recv_multipart()
        if parts[0] == protocol.LOG_TOPIC:
            try:
                e = protocol.decode_log(parts)
            except ValueError:
                continue
            if e.seq > last_seq and e.level >= min_level:        # the history may overlap the live feed
                print(logs.format_entry(e, with_date=True), flush=True)
            last_seq = max(last_seq, e.seq)
            continue
        header, p, flags = protocol.decode_frame_flags(parts)
        i = int(p.argmax())
        f_peak = header["f_start_hz"] + i * header["f_step_hz"]
        bad = f"  ({int((flags != 0).sum())} flagged)" if flags is not None and flags.any() else ""
        print(
            f"seq {header['seq']:5d}  atten {header['atten_db']:4.1f} dB  "
            f"peak {p[i]:7.2f} dBm @ {f_peak / 1e6:9.3f} MHz{bad}"
        )
        n += 1


if __name__ == "__main__":
    main()
