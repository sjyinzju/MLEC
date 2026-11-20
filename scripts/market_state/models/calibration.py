"""Deterministic per-class Platt sigmoids on time-out-of-fold decision scores."""
import numpy as np
import scipy
import warnings
from scipy.special import expit
from scipy.optimize import minimize
from .errors import FitFailure
import time


def decision_columns(scores, classes, class_count):
    classes = np.asarray(classes)
    if not np.array_equal(np.sort(classes), np.arange(class_count)) or len(np.unique(classes)) != class_count:
        raise FitFailure('Internal SVC must support every dictionary class', [])
    scores = np.asarray(scores, dtype='float64')
    if class_count == 2:
        if scores.ndim != 1:
            raise ValueError('Binary SVC requires one signed decision margin')
        scores = np.column_stack([-scores, scores])
    if scores.ndim != 2 or scores.shape[1] != class_count or not np.isfinite(scores).all():
        raise ValueError('Finite OVR decision columns required')
    return scores[:, np.argsort(classes)]


def sigmoid_objective(parameters, scores, smoothed_y):
    logits = parameters[0] * scores + parameters[1]
    value = np.sum(np.logaddexp(0., logits) - smoothed_y * logits)
    residual = expit(logits) - smoothed_y
    return float(value), np.array([np.dot(residual, scores), residual.sum()])


class TimeSigmoid:
    def __init__(self, rules):
        self.rules = dict(rules)
        self.diagnostics_ = []

    def optimize(self, x, target, initial):
        return minimize(sigmoid_objective, initial, args=(x, target), method='L-BFGS-B', jac=True,
            options={k: self.rules[k] for k in ['ftol', 'gtol', 'maxls']} | {'maxiter': self.rules['max_iter']})

    def polish(self, parameters, x, target, threshold):
        """Bounded same-objective Newton; explicit real optimization, blocked in pytest."""
        parameters = parameters.copy()
        objective, gradient = sigmoid_objective(parameters, x, target)
        for iteration in range(self.rules.get('newton_steps', 20)):
            if np.max(np.abs(gradient)) <= threshold:
                return parameters, objective, gradient, iteration
            p = expit(parameters[0]*x+parameters[1])
            design = np.column_stack([x,np.ones(len(x))])
            H = (design.T * (p*(1-p))) @ design
            step = np.linalg.lstsq(H, gradient, rcond=1e-14)[0]
            accepted = False
            for line in range(30):
                proposal = parameters-step*(.5**line)
                value, g = sigmoid_objective(proposal, x, target)
                if value <= objective-1e-4*(.5**line)*np.dot(gradient,step):
                    parameters, objective, gradient = proposal, value, g
                    accepted = True
                    break
            if not accepted:
                return parameters, objective, gradient, iteration+1
        return parameters, objective, gradient, self.rules.get('newton_steps', 20)

    def fit(self, scores, labels, class_ids):
        self.__dict__.pop('parameters_', None)
        self.diagnostics_ = []
        scores, labels = np.asarray(scores, dtype='float64'), np.asarray(labels)
        if scores.shape != (len(labels), len(class_ids)) or not np.isfinite(scores).all() or not np.isin(labels, class_ids).all():
            raise ValueError('Calibration score/label order mismatch')
        parameters = []
        for j, class_id in enumerate(class_ids):
            positive = int((labels == class_id).sum())
            negative = len(labels) - positive
            if min(positive, negative) < self.rules['min_oof_per_class']:
                raise FitFailure('Insufficient pooled time-OOF class support', self.diagnostics_)
            target = np.where(labels == class_id, (positive + 1.) / (positive + 2.), 1. / (negative + 2.))
            scale = max(1., float(np.max(np.abs(scores[:, j]))))
            start = time.perf_counter()
            record = dict(component='calibrator', target=str(class_id), attempt=1, warnings=[], converged=False,
                positive=positive, negative=negative, score_scale=scale, max_iter=self.rules['max_iter'])
            self.diagnostics_.append(record)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                try:
                    result = self.optimize(scores[:, j] / scale, target, np.array([0., np.log((positive + 1.) / (negative + 1.))]))
                except BaseException as error:
                    record.update(error=type(error).__name__ + ': ' + str(error),
                        elapsed_seconds=time.perf_counter()-start,
                        warnings=[dict(category=w.category.__name__, message=str(w.message)) for w in caught])
                    if not isinstance(error, Exception) or isinstance(error, (MemoryError,OSError)):
                        error.diagnostics=self.diagnostics_
                        raise
                    raise FitFailure('Sigmoid optimization failed', self.diagnostics_) from error
            record['warnings'] = [dict(category=w.category.__name__, message=str(w.message)) for w in caught]
            numerical = not (np.isfinite(result.x).all() and np.isfinite(result.fun) and np.isfinite(result.jac).all()) or any(issubclass(w.category, RuntimeWarning) for w in caught)
            # Independently recompute the convex objective and its gradient.
            x = scores[:, j] / scale
            objective, gradient = sigmoid_objective(result.x, x, target)
            baseline, _ = sigmoid_objective(np.array([0., np.log(target.mean()/(1-target.mean()))]), x, target)
            threshold = self.rules.get('optimality_gradient', self.rules['gtol'])
            optimal = np.max(np.abs(gradient)) <= threshold and objective <= baseline + 1e-10*max(1,baseline)
            corrections = 0
            if bool(result.success) and not numerical and not optimal:
                try:
                    result.x, objective, gradient, corrections = self.polish(result.x, x, target, threshold)
                except Exception as error:
                    record.update(error=str(error),elapsed_seconds=time.perf_counter()-start)
                    if isinstance(error,(MemoryError,OSError)):
                        error.diagnostics=self.diagnostics_
                        raise
                    raise FitFailure('Sigmoid same-objective correction failed',self.diagnostics_) from error
                optimal = np.max(np.abs(gradient)) <= threshold and objective <= baseline+1e-10*max(1,baseline)
            certified = bool(result.success) and bool(optimal)
            record.update(converged=certified and not numerical, numerical_failure=numerical,
                n_iter=int(result.nit), status=int(result.status), message=str(result.message),
                objective=float(result.fun) if np.isfinite(result.fun) else None,
                gradient_max=float(np.max(np.abs(gradient))) if np.isfinite(gradient).all() else None,
                quality=dict(accepted=bool(optimal), objective=float(objective), intercept_only_objective=float(baseline),
                    gradient_threshold=threshold, newton_corrections=corrections),
                slope=float(result.x[0]), intercept=float(result.x[1]), elapsed_seconds=time.perf_counter()-start,
                support_status='LEGAL_BUT_SPARSE_UNSTABLE' if min(positive,negative)<20 else 'LEGAL_SUPPORT')
            if not record['converged']:
                raise FitFailure('Sigmoid did not converge; no fallback algorithm', self.diagnostics_)
            parameters.append(dict(class_id=int(class_id), slope=float(result.x[0]), intercept=float(result.x[1]), scale=scale))
        self.parameters_ = parameters
        return self

    def predict_proba(self, scores):
        scores = np.asarray(scores, dtype='float64')
        if not hasattr(self, 'parameters_') or scores.ndim != 2 or scores.shape[1] != len(self.parameters_) or not np.isfinite(scores).all():
            raise ValueError('Unfitted calibrator or invalid decision columns')
        p = np.column_stack([expit(d['slope'] * (scores[:, j] / d['scale']) + d['intercept']) for j, d in enumerate(self.parameters_)])
        p = np.clip(p, self.rules['probability_floor'], 1. - self.rules['probability_floor'])
        return p / p.sum(axis=1, keepdims=True)

    def state(self):
        return dict(version=self.rules['version'], scipy_version=scipy.__version__, rules=self.rules,
            parameters=self.parameters_, diagnostics=self.diagnostics_)

    @classmethod
    def from_state(cls, state, rules):
        if state['version'] != rules['version'] or state['rules'] != rules or state['scipy_version'] != scipy.__version__:
            raise ValueError('Calibrator version/rules differ')
        result = cls(rules)
        result.parameters_, result.diagnostics_ = state['parameters'], state['diagnostics']
        return result
