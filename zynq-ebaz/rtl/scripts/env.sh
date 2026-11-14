# Sourced by the other scripts: paths and tool settings of the RTL lane.
# Override any of these in the environment before calling a script.
: "${VIVADO_ROOT:=/media/patrik/Workspaces/Tools/HW/Xilinx/2025.2/Vivado}"
: "${SADIY_VIVADO_DIR:=/media/patrik/Workspaces/HW/Vivado/EBAZ_SAdiy}"   # generated Vivado project
: "${SADIY_JOBS:=8}"                                                      # plan 1a: at most 8 threads per run

SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RTL_DIR="$(cd "$SCRIPTS_DIR/.." && pwd)"
EBAZ_DIR="$(cd "$RTL_DIR/.." && pwd)"
REPO_DIR="$(cd "$EBAZ_DIR/.." && pwd)"
BUILD_DIR="$EBAZ_DIR/build"

# Python: the repo's venv lives in the main checkout (worktrees share it); fall back to python3.
if [ -z "${PYTHON:-}" ]; then
  for p in "$REPO_DIR/.venv/bin/python" "$REPO_DIR/../SAdiy/.venv/bin/python"; do
    [ -x "$p" ] && PYTHON="$p" && break
  done
  : "${PYTHON:=python3}"
fi

vivado_env() {
  if ! command -v xvlog >/dev/null 2>&1; then
    # shellcheck disable=SC1091
    source "$VIVADO_ROOT/settings64.sh"
  fi
}
export VIVADO_ROOT SADIY_VIVADO_DIR SADIY_JOBS RTL_DIR EBAZ_DIR REPO_DIR BUILD_DIR PYTHON
