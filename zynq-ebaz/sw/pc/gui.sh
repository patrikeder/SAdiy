#!/bin/sh
# GUI on the PC for the EBAZ4205. Run from anywhere inside the checkout, with the virtual environment active (or .venv next to it).
#   sh zynq-ebaz/sw/pc/gui.sh <ebaz-ip>        connect to a running sweepd (./bench.sh or ./sweep.sh on the board)
#   sh zynq-ebaz/sw/pc/gui.sh --sim            own simulator, no board
ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$ROOT" || exit 1
[ -n "$VIRTUAL_ENV" ] || { [ -f .venv/bin/activate ] && . .venv/bin/activate; }
case "${1:-}" in
    "") echo "usage: sh zynq-ebaz/sw/pc/gui.sh <ebaz-ip> | --sim" >&2; exit 2 ;;
    --sim) exec python -m sadiy.ui.sa_gui --platform ebaz --sim ;;
    *) exec python -m sadiy.ui.sa_gui --platform ebaz --host "$1" --connect ;;
esac
