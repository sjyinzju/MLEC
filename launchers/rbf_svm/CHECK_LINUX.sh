#!/usr/bin/env bash
# Mirror of CHECK_WINDOWS.cmd for Linux: environment, data and interface checks only.
# Nothing here may fit a supervised estimator; the formal run is START_LINUX.sh.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -f config/experiments/rbf_svm.yaml ]]; then cd ../..; fi
echo 'MLEC RBF-SVM: CHECK ONLY, no supervised fitting.'
check='import sys,struct; assert sys.version_info[:2]==(3,11) and struct.calcsize("P")==8, "64-bit Python 3.11 required"'
if [[ -n "${MLEC_PYTHON:-}" ]]; then
  task_python="$MLEC_PYTHON"
else
  task_python="$PWD/.venv-rbf-svm/bin/python"
  if [[ ! -x "$task_python" ]]; then
    "${PYTHON:-python3.11}" -c "$check" || { echo 'Install 64-bit Python 3.11 and its venv module, or set MLEC_PYTHON.'; exit 1; }
    "${PYTHON:-python3.11}" -m venv .venv-rbf-svm || { echo 'Cannot create venv; check write permissions and Python venv support.'; exit 1; }
  fi
fi
"$task_python" -c "$check"
if ! "$task_python" -c 'from scripts.market_state.experiments.runtime import environment; environment()' >/dev/null 2>&1; then
  "$task_python" -m pip install --disable-pip-version-check -r requirements-experiments.txt || { echo 'Installation failed; check internet/proxy or configure a package mirror, then restart.'; exit 1; }
fi
"$task_python" -c 'from scripts.market_state.experiments.runtime import environment; environment()'
"$task_python" -m scripts.market_state.experiments preflight --model rbf_svm "$@"
echo 'Checks passed. No supervised fitting was started.'
