#!/usr/bin/env bash
# SENTIR - compila o BrainFlow com o driver MeowerBoard (Linux) e instala o pacote Python.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BF="${1:-$HERE/../_deps/brainflow}"
[ -d "$BF" ] || git clone https://github.com/brainflow-dev/brainflow.git "$BF"
python3 "$HERE/integrate_meower.py" "$BF"
cd "$BF"
python3 tools/build.py --no-synchroni --no-tests --num-jobs "$(nproc)"
python3 -m pip install --upgrade ./python_package
python3 -c "from brainflow.board_shim import BoardIds; print('MEOWER_BOARD =', int(BoardIds.MEOWER_BOARD))"
