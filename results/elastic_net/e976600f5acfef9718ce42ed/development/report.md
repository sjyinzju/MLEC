# elastic_net: development

run_id: `e976600f5acfef9718ce42ed`; purpose: `RESEARCH`; suite: `core`.

Development results were used for selection and warning workpoints; test results are time-forward evaluations of the locked plan.

## Prediction performance

See [classification](tables/core_classification.md) and [seven-target regression](tables/core_regression.md). The `mean` seed rows average losses/metrics, not probabilities. `n` counts dated windows once.

Naive historical frequency, current memberships/state persistence and past-20-day continuous persistence are included. Core models retain all seven targets and report original-unit errors.

## Macro increment

- 000852.SH classification: -0.0120675, 95% interval [-0.0529918, 0.0288222]; HIGHER_LOSS_WITH_MACRO.
- 000985.SH regression: 0.000204803, 95% interval [-1.63835e-06, 0.000366136]; SMALL_RELATIVE_EFFECT_BELOW_0.1_PERCENT.
- 000300.SH classification: -0.0177724, 95% interval [-0.0993505, 0.0379351]; HIGHER_LOSS_WITH_MACRO.
- 000905.SH classification: -0.0161001, 95% interval [-0.0684732, 0.0335027]; HIGHER_LOSS_WITH_MACRO.
- 000985.SH classification: -0.0446133, 95% interval [-0.140765, 0.0211373]; HIGHER_LOSS_WITH_MACRO.
- 000852.SH regression: 0, 95% interval [0, 0]; NUMERICALLY_EQUIVALENT.
- 000905.SH regression: -0.0470339, 95% interval [-0.0998593, -0.00451101]; HIGHER_LOSS_WITH_MACRO.
- 000300.SH regression: -0.0417366, 95% interval [-0.088931, -0.00510616]; HIGHER_LOSS_WITH_MACRO.

Intervals use synchronous calendar blocks, including empty weeks; centered-null one-sided p values use finite-repetition correction. Annual results and 4/12-week sensitivities accompany the 8-week primary block. Accuracy/F1 gains are right-minus-left aggregate metrics; intervals in each row refer only to the named sample loss.

Elastic Net is the linear reference. Cross-model Holm correction is pending the complete preregistered nonlinear family set; no adjusted value is fabricated.

## Warning value

See [warning workpoints](tables/warning_value.md). Burden targets 5/10/20/30% were specified before execution; thresholds come only from development. Detection–false alarm, precision–recall and drawdown coverage–burden curves are saved. Alarm segments and repeat windows are separate from window metrics. Undefined event contrasts are reported explicitly; no unique economic optimum or crisis lead time is claimed.

## Coverage and limits

Selected logical monthly tasks: 1584; unique physical fits: 1584. Unscored prediction rows across analysis references: 176; these are immature windows, not normal-state labels or failed predictions.

Runtime quality includes failed candidates, actual estimator/calibrator calls, convergence retries and economic boundary violations. Penalized coefficients describe prediction associations, not causal effects.

Completed core suite only: M/M+Z; all 96 fixed_full_params configurations were NOT EXECUTED. Information-clock, publication-lag, market-module, data-view and alternative-dictionary extensions are unimplemented and were not executed. Registered unimplemented model families: random_forest, catboost. This report contains only the explicitly selected family/run.

The test era was viewed in the first Elastic Net run. This implementation correction is a recomputation after known defects, not a first unseen independent test. Numerical equivalence uses 128 machine eps times max(1, baseline loss); effects below 0.1% relative loss are labeled small, not erased. These descriptive labels do not change scores, candidate ranking or bootstrap calculations. Accuracy/argmax changes alone do not establish warning value; inspect probability losses, balanced accuracy, macro-F1, per-class recall and confusion together.

Data version: `5d57508f09249cf50b1a2e52`. Interface: `26d9fc0824f8f702707c0a17c3a1d68bef27d49089b59d767668252ece68ac12`. Experiment code: `09687dbb9847fb5907af622a66d8cbd07b40c655a5f88a82e3d382a2690568ef`.
