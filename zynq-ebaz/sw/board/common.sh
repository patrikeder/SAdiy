# Sourced by the scripts in ~/sadiy (fpga.sh, bench.sh, sweep.sh, sim.sh, status.sh, stop.sh). Not run by itself.
SADIY_HOME=${SADIY_HOME:-$(cd "$(dirname "$0")" && pwd)}
export PYTHONPATH="$SADIY_HOME/src:$SADIY_HOME/zynq-ebaz/sw${PYTHONPATH:+:$PYTHONPATH}"
BITSTREAM=${BITSTREAM:-$SADIY_HOME/fpga/ebaz_sadiy.bit.bin}
PROBE="$SADIY_HOME/zynq-ebaz/sw/tools/ebaz_pl_probe.py"
SADIY_CONFIG=${SADIY_CONFIG:-}

die() { echo "$(basename "$0"): $*" >&2; exit 1; }

as_root() {     # run a command as root, keeping PYTHONPATH (sudo drops it); SADIY_NO_SUDO=1 only in tests
    if [ "$(id -u)" = 0 ] || [ -n "$SADIY_NO_SUDO" ]; then "$@"; else sudo env PYTHONPATH="$PYTHONPATH" "$@"; fi
}

probe() { as_root python3 "$PROBE" $PROBE_ARGS "$@"; }       # PROBE_ARGS: tests only

sweepd_pids() {  # pids of running sweepd processes (not this shell); SADIY_PROC_PATTERN: tests only
    for d in /proc/[0-9]*; do
        p=${d#/proc/}
        [ "$p" = "$$" ] && continue
        argv0=$(tr '\0' '\n' <"$d/cmdline" 2>/dev/null | head -1)
        case "${argv0##*/}" in python*|sudo|env) ;; *) continue ;; esac      # not a shell or editor that merely mentions it
        tr '\0' ' ' <"$d/cmdline" 2>/dev/null | grep -q "${SADIY_PROC_PATTERN:-sadiy.server.sweepd}" && echo "$p"
    done
}

no_other_sweepd() {
    pids=$(sweepd_pids)
    [ -z "$pids" ] || die "sweepd is already running (pid $(echo $pids | tr ' ' ',')): stop it first with ./stop.sh"
}

banner() {      # which software: the build line
    python3 -m sadiy.buildinfo 2>/dev/null | sed 's/^/software: /'
}
