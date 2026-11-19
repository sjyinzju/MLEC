#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-experiments.txt
if [[ -f package.manifest.json ]]; then
  .venv/bin/python -m scripts.market_state.experiments.portable --verify .
fi
exec .venv/bin/python -m scripts.market_state.experiments preflight --model elastic_net "$@"
