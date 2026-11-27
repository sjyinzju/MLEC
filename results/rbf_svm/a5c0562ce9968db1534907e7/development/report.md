# rbf_svm: development

run_id: `a5c0562ce9968db1534907e7`; purpose: `RESEARCH`; suite: `core`.

Development results were used for selection and warning workpoints; test results are time-forward evaluations of the locked plan.

## Prediction performance

See [classification](tables/core_classification.md) and [seven-target regression](tables/core_regression.md). The `mean` seed rows average losses/metrics, not probabilities. `n` counts dated windows once.

Naive historical frequency, current memberships/state persistence and past-20-day continuous persistence are included. Core models retain all seven targets and report original-unit errors.

## Macro increment

- 000852.SH classification: -0.00245178, 95% interval [-0.032713, 0.0248489]; HIGHER_LOSS_WITH_MACRO.
- 000985.SH classification: -0.00228915, 95% interval [-0.00497268, -0.000431426]; HIGHER_LOSS_WITH_MACRO.
- 000852.SH regression: -0.0101758, 95% interval [-0.0185535, -0.00494139]; HIGHER_LOSS_WITH_MACRO.
- 000905.SH classification: 0.00846136, 95% interval [0.00376054, 0.0132013]; LOWER_LOSS_WITH_MACRO.
- 000985.SH regression: -0.00205188, 95% interval [-0.0314372, 0.0204544]; HIGHER_LOSS_WITH_MACRO.
- 000905.SH regression: -0.0269083, 95% interval [-0.0633972, -0.00101754]; HIGHER_LOSS_WITH_MACRO.
- 000300.SH regression: -0.0114843, 95% interval [-0.039884, 0.00674061]; HIGHER_LOSS_WITH_MACRO.
- 000300.SH classification: 0.00438685, 95% interval [-0.00841768, 0.0273037]; LOWER_LOSS_WITH_MACRO.

Intervals use synchronous calendar blocks, including empty weeks; centered-null one-sided p values use finite-repetition correction. Annual results and 4/12-week sensitivities accompany the 8-week primary block. Accuracy/F1 gains are right-minus-left aggregate metrics; intervals in each row refer only to the named sample loss.

Elastic Net is the linear reference. Cross-model Holm correction is pending the complete preregistered nonlinear family set; no adjusted value is fabricated.

## Warning value

See [warning workpoints](tables/warning_value.md). Burden targets 5/10/20/30% were specified before execution; thresholds come only from development. Detection–false alarm, precision–recall and drawdown coverage–burden curves are saved. Alarm segments and repeat windows are separate from window metrics. Undefined event contrasts are reported explicitly; no unique economic optimum or crisis lead time is claimed.

## Coverage and limits

Selected logical monthly tasks: 1008; unique physical fits: 1008. Unscored prediction rows across analysis references: 112; these are immature windows, not normal-state labels or failed predictions.

Runtime quality includes failed candidates, actual estimator/calibrator calls, convergence retries and economic boundary violations. RBF-SVM records kernel scale, support counts, solver status and training-only time calibration; kernels have no linear coefficient interpretation.

Completed core suite only: M/M+Z; all 96 fixed_full_params configurations were NOT EXECUTED. Information-clock, publication-lag, market-module, data-view and alternative-dictionary extensions are unimplemented and were not executed. Registered unimplemented model families: random_forest, catboost. This report contains only the explicitly selected family/run.

The test era was viewed in the first Elastic Net run. This implementation correction is a recomputation after known defects, not a first unseen independent test. Numerical equivalence uses 128 machine eps times max(1, baseline loss); effects below 0.1% relative loss are labeled small, not erased. These descriptive labels do not change scores, candidate ranking or bootstrap calculations. Accuracy/argmax changes alone do not establish warning value; inspect probability losses, balanced accuracy, macro-F1, per-class recall and confusion together.

Data version: `5d57508f09249cf50b1a2e52`. Interface: `26d9fc0824f8f702707c0a17c3a1d68bef27d49089b59d767668252ece68ac12`. Experiment code: `768fb7e7d2f361b258372851f778d1bbf00628c5f55a13450c0858899d7500d2`.
