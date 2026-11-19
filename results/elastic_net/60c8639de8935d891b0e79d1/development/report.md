# elastic_net: development

run_id: `60c8639de8935d891b0e79d1`; purpose: `RESEARCH`; suite: `core`.

Development results were used for selection and warning workpoints; test results are time-forward evaluations of the locked plan.

## Prediction performance

See [classification](tables/core_classification.md) and [seven-target regression](tables/core_regression.md). The `mean` seed rows average losses/metrics, not probabilities. `n` counts dated windows once.

Naive historical frequency, current memberships/state persistence and past-20-day continuous persistence are included. Core models retain all seven targets and report original-unit errors.

## Macro increment

- 000852.SH classification: -0.000218, 95% interval [-0.000860129, 0.000336212]; higher loss with macro.
- 000985.SH regression: -9.5559e-05, 95% interval [-0.000198682, 1.89318e-05]; higher loss with macro.
- 000300.SH classification: 5.02855e-05, 95% interval [-4.55562e-05, 0.000143619]; lower loss with macro.
- 000905.SH classification: -3.87425e-05, 95% interval [-0.00100106, 0.00124309]; higher loss with macro.
- 000985.SH classification: 2.60372e-15, 95% interval [-5.12456e-19, 7.86218e-15]; lower loss with macro.
- 000852.SH regression: -4.93872e-05, 95% interval [-0.000146212, 1.27648e-05]; higher loss with macro.
- 000905.SH regression: -1.44743e-06, 95% interval [-1.71708e-05, 2.08686e-05]; higher loss with macro.
- 000300.SH regression: -0.0789737, 95% interval [-0.146733, -0.0190359]; higher loss with macro.

Intervals use synchronous calendar blocks, including empty weeks; centered-null one-sided p values use finite-repetition correction. Annual results and 4/12-week sensitivities accompany the 8-week primary block. Accuracy/F1 gains are right-minus-left aggregate metrics; intervals in each row refer only to the named sample loss.

Elastic Net is the linear reference. Cross-model Holm correction is pending the complete preregistered nonlinear family set; no adjusted value is fabricated.

## Warning value

See [warning workpoints](tables/warning_value.md). Burden targets 5/10/20/30% were specified before execution; thresholds come only from development. Detection–false alarm, precision–recall and drawdown coverage–burden curves are saved. Alarm segments and repeat windows are separate from window metrics. Undefined event contrasts are reported explicitly; no unique economic optimum or crisis lead time is claimed.

## Coverage and limits

Selected logical monthly tasks: 1584; unique physical fits: 1584. Unscored prediction rows across analysis references: 176; these are immature windows, not normal-state labels or failed predictions.

Runtime quality includes failed candidates, convergence warnings/retries and economic boundary violations. Penalized coefficients describe prediction associations, not causal effects.

The full suite covers twelve formal information sets in fixed_full_params. Information-clock, publication-lag, market-module, data-view and alternative-dictionary extensions are unimplemented and were not executed. Other three model families remain unimplemented; this is a single-family report.

Data version: `5d57508f09249cf50b1a2e52`. Interface: `f9ee345ef0af8b95aa11535f4fbcec7dc90da4a6328375356593f2668625e93b`. Experiment code: `3c5c7777a9a3a70faf0575e47e6e6c516050815702b5af35718712f1e288eb55`.
