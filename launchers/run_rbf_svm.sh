#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec "${PYTHON:-python3}" -m scripts.market_state.experiments pipeline \
  --model rbf_svm --config config/experiments/rbf_svm.yaml \
  --suite full --execute --resume "$@"
