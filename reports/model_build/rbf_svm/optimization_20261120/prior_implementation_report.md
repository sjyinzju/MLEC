# RBF-SVM implementation acceptance

Status: **IMPLEMENTED**. Construction only; no real supervised fit, calibration optimization, parameter search, smoke or formal BC experiment was executed.

The shared framework now separates family parameter/seed/solver rules, supports bounded Windows/Linux spawn workers, claims each physical fit, preserves failure budgets across analysis aliases, and coordinates atomic results and stable selection. Elastic Net configuration, candidate lists and its fixed delivered ZIP were preserved. Random Forest and CatBoost remain unimplemented.

RBF-SVC uses raw training-only time partitions, independently fitted input transforms, mature labels and per-class deterministic sigmoid calibration. Seven RBF-SVRs share the candidate and return checked original units. All rules, actual gamma, support counts, solver/calibration diagnostics and component versions are retained. The formal entry automatically executes B → validated lock → C → reports after a later explicit launch.

Verification: **148 passed** in the complete ordinary pytest suite, with real estimator fits and sigmoid optimization blocked. PowerShell parser and Bash -n passed. The formal non-training preflight passed for all 332 market/month training cohorts. These checks use non-learning stubs and do not establish real solver convergence or real serial/parallel numeric identity.

Data version: `5d57508f09249cf50b1a2e52`; unchanged seal SHA-256: `728d7adb6305f4951281c800c16508aa3fa1565e52dfbfd7e96f655100acce8f`. Interface code was unchanged and its acceptance revalidated. Full current identities, tests, expanded component budgets and preflight evidence are embedded in [acceptance.json](acceptance.json).

Start from `README_START_HERE.md` in the portable SVM ZIP. Require 64-bit Python 3.11 and first-use network access for pinned dependencies, or reuse a qualified environment. Return the entire `results/rbf_svm/<run_id>/` directory. Detailed preregistered rules: [docs/rbf_svm.md](../../../docs/rbf_svm.md).
