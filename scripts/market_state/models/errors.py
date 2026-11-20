"""Common model failure with an auditable record of actual solver attempts."""


class FitFailure(RuntimeError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics
        self.kind = ('NUMERICAL' if any(d.get('numerical_failure') for d in diagnostics) else
            'CONVERGENCE' if any(any(w.get('category') == 'ConvergenceWarning' for w in d.get('warnings', [])) for d in diagnostics) else
            'OPTIMALITY' if any(d.get('quality', {}).get('accepted') is False for d in diagnostics) else 'ESTIMATOR')


class ResourceFailure(RuntimeError):
    kind = 'RESOURCE'


def fit_counts(diagnostics):
    return dict(estimator_fit_calls=sum(d.get('component', 'estimator') != 'calibrator'
        and d.get('estimator_fit_called', True) for d in diagnostics),
        calibration_fit_calls=sum(d.get('component') == 'calibrator' for d in diagnostics))
