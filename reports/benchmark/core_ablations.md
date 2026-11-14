# Core leave-one-group-out results

| algorithm         | removed_group   | sample_version   |         mean |        lower |        upper |   block_weeks |   repetitions | method                      |
|:------------------|:----------------|:-----------------|-------------:|-------------:|-------------:|--------------:|--------------:|:----------------------------|
| gradient_boosting | credit          | common_core_v1   | -0.0067167   | -0.0346731   |  0.014869    |             8 |           500 | moving_calendar_week_blocks |
| gradient_boosting | growth          | common_core_v1   | -0.00534424  | -0.0117032   |  0.000704937 |             8 |           500 | moving_calendar_week_blocks |
| gradient_boosting | prices          | common_core_v1   |  0.00880359  | -0.0034899   |  0.0305291   |             8 |           500 | moving_calendar_week_blocks |
| gradient_boosting | rates_fx        | common_core_v1   | -0.0024185   | -0.00759675  |  0.00337804  |             8 |           500 | moving_calendar_week_blocks |
| historical_rate   | credit          | common_core_v1   |  0           |  0           |  0           |             8 |           500 | moving_calendar_week_blocks |
| historical_rate   | growth          | common_core_v1   |  0           |  0           |  0           |             8 |           500 | moving_calendar_week_blocks |
| historical_rate   | prices          | common_core_v1   |  0           |  0           |  0           |             8 |           500 | moving_calendar_week_blocks |
| historical_rate   | rates_fx        | common_core_v1   |  0           |  0           |  0           |             8 |           500 | moving_calendar_week_blocks |
| logistic          | credit          | common_core_v1   | -0.0132352   | -0.032149    |  0.000694563 |             8 |           500 | moving_calendar_week_blocks |
| logistic          | growth          | common_core_v1   | -4.78149e-05 | -9.17139e-05 | -1.7929e-05  |             8 |           500 | moving_calendar_week_blocks |
| logistic          | prices          | common_core_v1   | -0.00477945  | -0.00959445  |  0.00450847  |             8 |           500 | moving_calendar_week_blocks |
| logistic          | rates_fx        | common_core_v1   | -0.00936022  | -0.0376335   |  0.00910411  |             8 |           500 | moving_calendar_week_blocks |
| random_forest     | credit          | common_core_v1   | -0.00518136  | -0.0184295   |  0.00604643  |             8 |           500 | moving_calendar_week_blocks |
| random_forest     | growth          | common_core_v1   |  0.00609592  |  0.000470432 |  0.0150714   |             8 |           500 | moving_calendar_week_blocks |
| random_forest     | prices          | common_core_v1   |  0.0107018   |  0.00260675  |  0.0247374   |             8 |           500 | moving_calendar_week_blocks |
| random_forest     | rates_fx        | common_core_v1   | -0.0602114   | -0.0876523   | -0.0242493   |             8 |           500 | moving_calendar_week_blocks |

Same core sample IDs, labels and folds. Difference = loss without the group minus loss with the full core; positive values favor retaining that group. These are development-only exploratory comparisons, not causal effects.
