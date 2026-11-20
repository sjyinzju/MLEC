"""Independent training-only optimality checks for sklearn 1.8 objectives."""
import hashlib
import numpy as np
from scipy.special import logsumexp, expit
from ..common import digest

QUALITY_VERSION = 'elastic-optimality-v4'


def elastic_dual_state(theta, X, yc, l1, l2, *, hessian=False):
    """Negative Fenchel dual; evaluation/derivatives only, no fitting."""
    n = len(yc)
    u = X.T @ theta
    soft = np.sign(u) * np.maximum(np.abs(u)-l1, 0.)
    w = soft/l2
    value = float(n*np.dot(theta,theta)/2. - np.dot(yc,theta) + np.dot(soft,soft)/(2.*l2))
    gradient = n*theta + X@w - yc
    H = None
    if hessian:
        active = X[:, np.abs(u)>l1]
        H = n*np.eye(n) + active@active.T/l2
    return value, gradient, H, w


def weight_hash(estimators):
    """Hash prediction state, independent of strides, pickle memoization or views."""
    states = []
    for e in estimators:
        state = dict(estimator=type(e).__module__ + '.' + type(e).__qualname__)
        for name in ['coef_', 'intercept_', 'classes_', 'n_features_in_']:
            if hasattr(e, name):
                a = np.ascontiguousarray(np.asarray(getattr(e, name)))
                state[name] = dict(shape=list(a.shape), dtype=a.dtype.str,
                    sha256=hashlib.sha256(a.tobytes(order='C')).hexdigest())
        states.append(state)
    return digest(states)


def initial_intercept(estimator, X, y, class_weight):
    """Exact intercept optimum with all slopes constrained to zero."""
    classes, counts = np.unique(y, return_counts=True)
    frequency = counts / counts.sum() if class_weight is None else np.full(len(classes), 1. / len(classes))
    estimator.classes_ = classes
    estimator.coef_ = np.zeros((1 if len(classes) == 2 else len(classes), X.shape[1]), dtype=float)
    estimator.intercept_ = np.array([np.log(frequency[1] / frequency[0])]) if len(classes) == 2 else np.log(frequency) - np.log(frequency).mean()


def classification_quality(estimator, X, y, parameters, class_weight=None):
    x, y = np.asarray(X, float), np.asarray(y)
    classes = np.asarray(estimator.classes_)
    if not np.array_equal(classes, np.unique(y)) or len(classes) < 2:
        raise ValueError('Fitted classes differ from observed training classes')
    index = np.searchsorted(classes, y)
    counts = np.bincount(index, minlength=len(classes))
    weights = np.ones(len(y)) if class_weight is None else len(y) / (len(classes) * counts[index])
    frequency = np.bincount(index, weights=weights, minlength=len(classes)) / weights.sum()
    logits = x @ estimator.coef_.T + estimator.intercept_
    binary = len(classes) == 2
    if binary:
        logits = logits.ravel()
        probability = expit(logits)
        log_loss = float(np.mean(weights * (np.logaddexp(0., logits) - index * logits)))
        errors = (probability - index) * weights
        residual = np.array([-errors.mean(), errors.mean()])
        gradient = (errors @ x / len(y))[None, :]
        means = np.array([1. - np.average(probability, weights=weights), np.average(probability, weights=weights)])
    else:
        logp = logits - logsumexp(logits, axis=1, keepdims=True)
        probability = np.exp(logp)
        log_loss = float(-np.mean(weights * logp[np.arange(len(y)), index]))
        errors = probability.copy()
        errors[np.arange(len(y)), index] -= 1.
        errors *= weights[:, None]
        residual = errors.mean(axis=0)
        gradient = errors.T @ x / len(y)
        means = np.average(probability, axis=0, weights=weights)
    w = np.asarray(estimator.coef_)
    l1 = parameters['l1_ratio'] / (parameters['C'] * len(y))
    l2 = (1. - parameters['l1_ratio']) / (parameters['C'] * len(y))
    objective = log_loss + l1 * np.abs(w).sum() + .5 * l2 * np.square(w).sum()
    baseline = float(-np.sum(frequency * np.log(frequency)))
    max_smooth_gradient = float(np.abs(gradient).max(initial=0.))
    gradient += l2 * w
    violation = np.where(w != 0., np.abs(gradient + l1 * np.sign(w)), np.maximum(np.abs(gradient) - l1, 0.))
    # Absolute mean-loss gradient tolerances, fixed from solver tol before any
    # scoring data are read. Baseline comparison allows only solver-size error.
    threshold = max(1e-5, 10. * parameters['tol'])
    objective_slack = max(1e-10, parameters['tol'] * max(1., baseline))
    worst = float(np.abs(residual).max())
    kkt = float(violation.max(initial=0.))
    values = [log_loss, objective, baseline, worst, kkt]
    probability_finite = bool(np.isfinite(probability).all())
    return dict(version=QUALITY_VERSION, accepted=bool(probability_finite and np.isfinite(values).all() and worst <= threshold
        and kkt <= threshold and objective <= baseline + objective_slack),
        classes=classes.tolist(), empirical_frequency=(counts / len(y)).tolist(), weighted_frequency=frequency.tolist(),
        mean_probability=means.tolist(), intercept_residual=residual.tolist(), max_intercept_residual=worst,
        training_log_loss=log_loss, objective=float(objective), intercept_only_objective=baseline,
        objective_excess=float(objective - baseline), objective_slack=objective_slack,
        kkt_max=kkt, gradient_tolerance=threshold,
        training_probability_finite=probability_finite, max_smooth_gradient=max_smooth_gradient,
        l1_penalty=l1, l2_penalty=l2,
        objective_definition='mean(weighted NLL) + (l1_ratio*L1 + (1-l1_ratio)*L2_squared/2)/(C*n)',
        intercept=np.asarray(estimator.intercept_).tolist())


def certify_zero_slopes(estimator, X, y, parameters, class_weight):
    initial_intercept(estimator, X, y, class_weight)
    quality = classification_quality(estimator, X, y, parameters, class_weight)
    # The penalized objective is convex. At zero slopes the subgradient
    # interval is [-l1, l1]. Use its exact bound, not the solver's KKT slack.
    if (quality['accepted'] and quality['max_smooth_gradient'] <= quality['l1_penalty']
            and quality['max_intercept_residual'] <= 16 * np.finfo(float).eps
            and abs(quality['objective_excess']) <= 16 * np.finfo(float).eps):
        estimator.n_features_in_ = X.shape[1]
        estimator.feature_names_in_ = np.asarray(X.columns, dtype=object)
        estimator.n_iter_ = np.zeros(1, dtype=np.int32)
        return quality
    return None


def regression_quality(estimator, X, y, parameters):
    x, y = np.asarray(X, float), np.asarray(y, float)
    w = np.asarray(estimator.coef_)
    yc, xc = y - y.mean(), x - x.mean(axis=0)
    residual = y - (x @ w + estimator.intercept_)
    n = len(y)
    l1, l2 = parameters['alpha'] * parameters['l1_ratio'], parameters['alpha'] * (1. - parameters['l1_ratio'])
    primal = float(np.square(residual).mean() / 2. + l1 * np.abs(w).sum() + l2 * np.square(w).sum() / 2.)
    # Elastic Net as Lasso on augmented [X; sqrt(n*l2)*I]. This supplies an
    # independently recomputed feasible dual, including the unpenalized intercept.
    dual_norm = float(np.abs(xc.T @ residual - n * l2 * w).max(initial=0.))
    factor = min(1., n * l1 / dual_norm) if dual_norm else 1.
    gap = float((.5 * np.square(residual).sum() * (1. + factor ** 2) + n * l1 * np.abs(w).sum()
        - factor * np.dot(residual, yc) + .5 * n * l2 * (1. + factor ** 2) * np.square(w).sum()) / n)
    augmented_gap = gap
    certificate_hash = None
    if hasattr(estimator, 'dual_certificate_'):
        theta = np.asarray(estimator.dual_certificate_, dtype=float).copy()
        if theta.shape != y.shape or not np.isfinite(theta).all():
            raise ValueError('Invalid training dual certificate')
        theta -= theta.mean()  # free-intercept feasibility, to floating precision
        if l2 > 0:
            negative_dual, _, _, _ = elastic_dual_state(theta, xc, yc, l1, l2)
        else:
            if np.abs(xc.T@theta).max(initial=0.) > l1 + 100.*np.finfo(float).eps*max(1.,l1):
                raise ValueError('Infeasible pure L1 dual certificate')
            negative_dual = float(n*np.dot(theta,theta)/2.-np.dot(yc,theta))
        gap = float(primal + negative_dual)
        certificate_hash = hashlib.sha256(np.ascontiguousarray(theta).tobytes()).hexdigest()
    gradient = -xc.T @ residual / n + l2 * w
    violation = np.where(w != 0., np.abs(gradient + l1 * np.sign(w)), np.maximum(np.abs(gradient) - l1, 0.))
    tolerance = float(parameters['tol'] * np.square(yc).mean())
    roundoff = float(100. * np.finfo(float).eps * max(1., primal, np.square(yc).mean()))
    reported = float(estimator.dual_gap_) if hasattr(estimator, 'dual_gap_') else None
    intercept_error = float(abs(residual.mean()))
    baseline = float(np.square(yc).mean() / 2.)
    finite = np.isfinite([primal, gap, intercept_error] + ([] if reported is None else [reported])).all()
    return dict(version=QUALITY_VERSION, accepted=bool(finite and -roundoff <= gap <= tolerance + roundoff
        and (reported is None or (-roundoff <= reported <= tolerance + roundoff and abs(gap - reported) <= roundoff * 10.))
        and intercept_error <= 1e-8 * max(1., float(np.std(y))) and primal <= baseline + roundoff),
        primal_objective=primal, dual_objective=primal-gap, independently_computed_dual_gap=gap,
        augmented_lasso_dual_gap=augmented_gap, dual_certificate_hash=certificate_hash,
        reported_dual_gap=reported, dual_gap_tolerance=tolerance, roundoff_allowance=roundoff,
        reported_dual_gap_available=reported is not None,
        intercept_residual=intercept_error, kkt_max=float(violation.max(initial=0.)), intercept_only_objective=baseline,
        objective_definition='squared_error/(2*n) + alpha*l1_ratio*L1 + alpha*(1-l1_ratio)*L2_squared/2')
