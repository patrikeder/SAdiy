"""Starts and stops a simulated-hardware `sweepd --sim` process for the GUI (Qt-free).

The daemon runs as a separate process, like on the BBB, so the plot can never stall the sweep. The
GUI only passes ports and simulator parameters through a temporary TOML file that
`config.load()` merges over `config/default.toml`.
"""
from __future__ import annotations

import collections
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Deque, List, Optional, Sequence, Tuple

Tone = Tuple[float, float]   # (frequency Hz, level dBm at the analyzer input)


def render_override(
    pub_port: int,
    rep_port: int,
    tones: Sequence[Tone],
    noise_dbm_in: float = -100.0,
    rbw_hz: float = 230e3,
    bind: str = "127.0.0.1",
) -> str:
    tone_list = ", ".join(f"[{float(f)!r}, {float(p)!r}]" for f, p in tones)
    return (
        "[server]\n"
        f'pub = "tcp://{bind}:{int(pub_port)}"\n'
        f'rep = "tcp://{bind}:{int(rep_port)}"\n'
        "\n[sim]\n"
        f"tones = [{tone_list}]\n"
        f"noise_dbm_in = {float(noise_dbm_in)!r}\n"
        f"rbw_hz = {float(rbw_hz)!r}\n"
    )


def _src_dir() -> str:
    return str(Path(__file__).resolve().parents[2])   # .../src, so a plain checkout works too


class SimRunner:
    def __init__(self, log_lines: int = 500) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._cfg_path: Optional[str] = None
        self._log: Deque[str] = collections.deque(maxlen=log_lines)
        self._lock = threading.Lock()
        self._reader: Optional[threading.Thread] = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None else None

    @property
    def returncode(self) -> Optional[int]:
        return None if self._proc is None else self._proc.poll()

    def build_command(self, cfg_path: str, period_s: float) -> List[str]:
        return [
            sys.executable, "-u", "-m", "sadiy.server.sweepd",
            "--sim", "--period", f"{period_s:g}", "--config", cfg_path,
        ]

    def start(
        self,
        pub_port: int,
        rep_port: int,
        period_s: float,
        tones: Sequence[Tone],
        noise_dbm_in: float = -100.0,
        rbw_hz: float = 230e3,
        command: Optional[List[str]] = None,
    ) -> None:
        """`command` replaces the daemon command line (tests only)."""
        if self.running:
            raise RuntimeError("simulated hardware is already running")
        self._cleanup_cfg()
        fd, self._cfg_path = tempfile.mkstemp(prefix="sadiy-sim-", suffix=".toml")
        with os.fdopen(fd, "w") as fh:
            fh.write(render_override(pub_port, rep_port, tones, noise_dbm_in, rbw_hz))
        argv = command if command is not None else self.build_command(self._cfg_path, period_s)
        env = dict(os.environ)
        env["PYTHONPATH"] = _src_dir() + os.pathsep + env.get("PYTHONPATH", "")
        with self._lock:
            self._log.clear()
            self._log.append("$ " + " ".join(argv))
        self._proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
        )
        self._reader = threading.Thread(target=self._pump, args=(self._proc,), daemon=True)
        self._reader.start()

    def _pump(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:           # ends when the process closes its pipe
            with self._lock:
                self._log.append(line.rstrip("\n"))

    def drain_log(self) -> List[str]:
        with self._lock:
            return list(self._log)

    def stop(self, timeout_s: float = 2.0) -> None:
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout_s)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        if self._reader is not None:
            self._reader.join(timeout=1.0)
        with self._lock:
            if proc is not None:
                self._log.append(f"[exited with code {proc.returncode}]")
        self._cleanup_cfg()

    def _cleanup_cfg(self) -> None:
        if self._cfg_path:
            try:
                os.unlink(self._cfg_path)
            except OSError:
                pass
            self._cfg_path = None
