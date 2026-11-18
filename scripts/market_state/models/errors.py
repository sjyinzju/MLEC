"""Common model failure with an auditable record of actual solver attempts."""


class FitFailure(RuntimeError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def fit_counts(diagnostics):
    return dict(estimator_fit_calls=sum(d.get('component', 'estimator') != 'calibrator' for d in diagnostics),
        calibration_fit_calls=sum(d.get('component') == 'calibrator' for d in diagnostics))
