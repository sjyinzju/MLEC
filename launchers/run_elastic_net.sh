#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
exec "${PYTHON:-python}" -m scripts.market_state.experiments pipeline \
  --model elastic_net --config config/experiments/elastic_net.yaml \
  --suite full --execute --resume "$@"
