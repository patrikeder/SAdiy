#!/usr/bin/env bash
# Regenerate everything generated from the Python side: register files (if the generator exists) and the golden
# vectors. `gen.sh --check` writes nothing and fails when a committed file is out of date.
set -euo pipefail
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

mode=()
case "${1:-}" in
  "") ;;
  --check) mode=(--check) ;;
  *) echo "usage: gen.sh [--check]" >&2; exit 2 ;;
esac

if [ -f "$RTL_DIR/regmap/gen_regs.py" ]; then
  "$PYTHON" "$RTL_DIR/regmap/gen_regs.py" "${mode[@]}"
fi
"$PYTHON" "$RTL_DIR/sim/gen_vectors.py" "${mode[@]}"
