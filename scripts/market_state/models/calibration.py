"""Deterministic per-class Platt sigmoids on time-out-of-fold decision scores."""
import numpy as np
import scipy
import warnings
from scipy.special import expit, logsumexp, softmax
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


def local_optimality(parameters, x, target, threshold):
    """Float64 local evidence, NOT a rigorous global error certificate."""
    objective, gradient = sigmoid_objective(parameters, x, target)
    design = np.column_stack([x,np.ones(len(x))])
    p = expit(design@parameters); w = p*(1-p)
    H = (design.T*w)@design
    eigen, vectors = np.linalg.eigh(H)
    largest = max(0.,float(eigen[-1])); resolution = np.finfo(float).eps*max(1.,abs(objective))
    heuristic = float(np.sqrt(2*largest*resolution))
    active = eigen > max(np.finfo(float).tiny,64*np.finfo(float).eps*largest)
    projected = vectors.T@gradient
    null_residual = float(np.max(np.abs(projected[~active]),initial=0))
    roundoff = 32*np.finfo(float).eps*max(1.,float(np.abs(p-target).sum()))
    direction = -(vectors[:,active] @ (projected[active]/eigen[active]))
    u = design@direction
    decrement = float(-gradient@direction/2)
    local = bool(np.max(np.abs(u),initial=0)<=1e-3)
    # Stable softplus Bregman remainder. Terms through order six; for |u|<=1e-3
    # the omitted seventh order is below the objective's float64 resolution.
    remainder = w*(u*u/2+(1-2*p)*u**3/6+(1-6*w)*u**4/24+
        (1-2*p)*(1-12*w)*u**5/120+(1-30*w+120*w*w)*u**6/720)
    delta = float(gradient@direction+remainder.sum()) if local else None
    descent = max(0.,-delta) if delta is not None else None
    second_order = local and null_residual<=roundoff and decrement<=8*resolution and descent<=8*resolution
    gradient_ok = np.max(np.abs(gradient))<=max(threshold,heuristic)
    accepted = bool(gradient_ok and second_order)
    return dict(accepted=accepted,configured_gradient_threshold=float(threshold),gradient_max=float(np.max(np.abs(gradient))),
        machine_attainable_gradient=heuristic,objective_resolution=float(resolution),objective=float(objective),
        hessian_eigenvalues=eigen.tolist(),hessian_max_eigenvalue=largest,
        hessian_condition=float(eigen[-1]/eigen[0]) if eigen[0]>0 else None,
        newton_decrement=decrement,newton_directional_change=delta,local_step=local,
        null_gradient=null_residual,null_gradient_roundoff=float(roundoff),
        criterion='absolute_and_local_second_order' if np.max(np.abs(gradient))<=threshold else 'float64_local_second_order',
        rigorous_global_certificate=False)


class TimeSigmoid:
    def __init__(self, rules):
        self.rules = dict(rules)
        self.diagnostics_ = []

    def optimize(self, x, target, initial):
        return minimize(sigmoid_objective, initial, args=(x, target), method='L-BFGS-B', jac=True,
            options={k: self.rules[k] for k in ['ftol', 'gtol', 'maxls']} | {'maxiter': self.rules['max_iter']})

    @staticmethod
    def attainable_gradient(parameters, x, objective):
        """Curvature-based resolution heuristic; not an optimality certificate.

        The objective is a *sum*. Its objective resolution is approximately
        eps*|f|. Curvature gives a diagnostic gradient scale, but cannot bound
        descent along weak-curvature directions. local_optimality checks those
        separately; this heuristic alone never authorizes acceptance.
        """
        p = expit(parameters[0] * x + parameters[1])
        weight = p * (1.0 - p)
        design = np.column_stack([x, np.ones(len(x))])
        hessian = (design.T * weight) @ design
        largest = float(np.linalg.eigvalsh(hessian)[-1])
        resolution = np.finfo(float).eps * max(1.0, abs(float(objective)))
        return float(np.sqrt(2.0 * max(largest, 0.0) * resolution)), largest, resolution

    def polish(self, parameters, x, target, threshold):
        """Bounded same-objective Newton; explicit real optimization, blocked in pytest."""
        parameters = parameters.copy()
        objective, gradient = sigmoid_objective(parameters, x, target)
        for iteration in range(self.rules.get('newton_steps', 20)):
            if local_optimality(parameters,x,target,threshold)['accepted']:
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
            evidence = local_optimality(result.x,x,target,threshold)
            optimal = evidence['accepted'] and objective <= baseline + 1e-10*max(1,baseline)
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
                evidence = local_optimality(result.x,x,target,threshold)
                optimal = evidence['accepted'] and objective <= baseline+1e-10*max(1,baseline)
            certified = bool(result.success) and bool(optimal)
            record.update(converged=certified and not numerical, numerical_failure=numerical,
                n_iter=int(result.nit), status=int(result.status), message=str(result.message),
                optimizer_objective=float(result.fun) if np.isfinite(result.fun) else None,
                optimizer_gradient_max=float(np.max(np.abs(result.jac))) if np.isfinite(result.jac).all() else None,
                objective=float(objective) if np.isfinite(objective) else None,
                gradient_max=float(np.max(np.abs(gradient))) if np.isfinite(gradient).all() else None,
                quality=dict(evidence, accepted=bool(optimal),intercept_only_objective=float(baseline),newton_corrections=corrections),
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


class TimeShrinkage(TimeSigmoid):
    """Direct multiclass log loss with scores shrunk toward the mature OOF prior."""
    def fit(self, scores, labels, class_ids):
        self.__dict__.pop('parameters_', None)
        scores, labels = np.asarray(scores, dtype='float64'), np.asarray(labels)
        counts = np.asarray([(labels == c).sum() for c in class_ids])
        if scores.shape != (len(labels), len(class_ids)) or not np.isfinite(scores).all() or counts.sum() != len(labels):
            raise ValueError('Calibration score/label order mismatch')
        if (np.minimum(counts, len(labels) - counts) < self.rules['min_oof_per_class']).any():
            raise FitFailure('Insufficient pooled time-OOF class support', [])
        center = scores.mean(axis=0)
        scale = np.maximum(scores.std(axis=0), self.rules['score_scale_floor'])
        z = (scores - center) / scale
        y = labels[:, None] == np.asarray(class_ids)
        prior = counts + self.rules['prior_alpha']
        log_prior = np.log(prior / prior.sum())
        penalty = np.array([[self.rules['slope_penalty']], [self.rules['offset_penalty']]])

        def objective(theta):
            coefficients = theta.reshape(2, -1)
            logits = log_prior + coefficients[0] * z + coefficients[1]
            residual = softmax(logits, axis=1) - y
            loss = np.sum(logsumexp(logits, axis=1) - (y * logits).sum(axis=1))
            gradient = np.stack(((z * residual).sum(axis=0), residual.sum(axis=0)))
            return float(loss + .5 * np.sum(penalty * coefficients ** 2)), (gradient + penalty * coefficients).ravel()

        started = time.perf_counter()
        initial = np.zeros(2 * len(class_ids))
        result = minimize(objective, initial, jac=True, method='L-BFGS-B',
            options=dict(maxiter=self.rules['max_iter'], ftol=self.rules['ftol'], gtol=self.rules['gtol']))
        loss, gradient = objective(result.x)
        baseline, _ = objective(initial)
        accepted = bool(result.success and np.isfinite(loss) and np.max(np.abs(gradient)) <= 1e-4 and loss <= baseline)
        self.diagnostics_ = [dict(component='calibrator', target='multiclass', attempt=1,
            converged=accepted, numerical_failure=not np.isfinite(loss), warnings=[], n_iter=int(result.nit),
            elapsed_seconds=time.perf_counter() - started, natural_counts=counts.tolist(),
            prior=(prior / prior.sum()).tolist(), objective=loss,
            intercept_only_objective=baseline, gradient_max=float(np.max(np.abs(gradient))))]
        if not accepted:
            raise FitFailure('Regularized time calibration did not converge', self.diagnostics_)
        slope, offset = result.x.reshape(2, -1)
        self.parameters_ = dict(class_ids=list(class_ids), center=center.tolist(), scale=scale.tolist(),
            slope=slope.tolist(), intercept=(log_prior + offset).tolist())
        return self

    def predict_proba(self, scores):
        p = self.parameters_
        logits = (np.asarray(scores) - p['center']) / p['scale'] * p['slope'] + p['intercept']
        probability = np.clip(softmax(logits, axis=1), self.rules['probability_floor'], 1.)
        return probability / probability.sum(axis=1, keepdims=True)
