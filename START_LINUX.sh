#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
echo 'MLEC Elastic Net: starting this file authorizes the full B -> lock -> C experiment.'
if [[ ! -x .venv/bin/python ]]; then
  "${PYTHON:-python3}" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
  "${PYTHON:-python3}" -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-experiments.txt
export PYTHON="$PWD/.venv/bin/python"
exec bash launchers/run_elastic_net.sh "$@"
