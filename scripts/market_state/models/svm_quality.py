"""Predictive content identity and independent, train-only LIBSVM certificates."""
import hashlib
import numpy as np
from scipy.spatial.distance import cdist
from ..common import digest

QUALITY_VERSION = 'rbf-kkt-v1'


def array_state(a):
    a = np.ascontiguousarray(np.asarray(a))
    return dict(dtype=a.dtype.str, shape=list(a.shape), sha256=hashlib.sha256(a.tobytes()).hexdigest())


def weight_hash(estimators):
    fields = ['support_', 'support_vectors_', 'dual_coef_', '_dual_coef_', 'intercept_', '_intercept_',
        'classes_', 'n_support_', '_n_support', '_gamma', 'n_features_in_', 'shape_fit_', '_probA', '_probB']
    return digest([dict(kind=type(e).__module__+'.'+type(e).__qualname__,
        parameters=e.get_params() if hasattr(e, 'get_params') else {},
        state={k: array_state(getattr(e, k)) for k in fields if hasattr(e, k)}) for e in estimators])


def kernel_geometry(X, gamma):
    x = np.asarray(X, float)
    d = cdist(x, x, 'sqeuclidean')
    k = np.exp(-gamma*d)
    off = ~np.eye(len(x), dtype=bool)
    values = k[off]
    # Participation rank is a spectral summary without an O(n^3) eigendecomposition.
    return dict(gamma=float(gamma), distances_quantiles=np.quantile(d[off], [0,.01,.25,.5,.75,.99,1]).tolist(),
        kernel_off_diagonal_quantiles=np.quantile(values, [0,.01,.25,.5,.75,.99,1]).tolist(),
        participation_rank=float(len(x)**2 / np.square(k).sum()),
        exact_duplicate_fraction=float((d[off] == 0).mean()), near_duplicate_fraction=float((values > 1-1e-8).mean()),
        nearly_disjoint_fraction=float((values < 1e-8).mean()))


def solution_quality(e, X, y, *, class_weight=None, kernel=None):
    x, y = np.asarray(X, float), np.asarray(y)
    k = kernel if kernel is not None else np.exp(-e._gamma*cdist(x, x, 'sqeuclidean'))
    tol = 2*e.tol + 1e-8  # LIBSVM stopping interval + double precision kernel recomputation.
    records = []
    if not hasattr(e, 'classes_'):
        beta = np.zeros(len(x)); beta[e.support_] = e.dual_coef_[0]
        f = k@beta + float(e.intercept_[0]); r = f-y
        a = np.abs(beta); free = (a > 1e-10) & (a < e.C-1e-10)
        g = r + e.epsilon*np.sign(beta)
        violation = np.where(a <= 1e-10, np.maximum(np.abs(r)-e.epsilon, 0),
            np.where(free, np.abs(g), np.maximum(g*np.sign(beta), 0)))
        norm = float(beta@k@beta)
        primal = .5*norm + e.C*np.maximum(np.abs(r)-e.epsilon, 0).sum()
        dual = -.5*norm + y@beta - e.epsilon*a.sum()
        records.append(dict(kkt_max=float(violation.max(initial=0)), equality_residual=float(abs(beta.sum())),
            box_violation=float(np.maximum(a-e.C, 0).max(initial=0)), primal=float(primal), dual=float(dual), gap=float(primal-dual),
            target_std=float(y.std()), epsilon_over_target_std=float(e.epsilon/y.std()) if y.std()>0 else None,
            prediction_std=float(f.std()), support_fraction=len(e.support_)/len(y)))
    else:
        classes = e.classes_; starts = np.r_[0,np.cumsum(e.n_support_)]
        pair = 0
        for i in range(len(classes)):
            for j in range(i+1, len(classes)):
                mask = (y == classes[i]) | (y == classes[j]); idx = np.flatnonzero(mask)
                sign = np.where(y[mask] == classes[i], 1., -1.)
                beta = np.zeros(len(x))
                if len(classes) == 2:
                    beta[e.support_] = e.dual_coef_[0]; sign = -sign
                else:
                    beta[e.support_[starts[i]:starts[i+1]]] = e.dual_coef_[j-1, starts[i]:starts[i+1]]
                    beta[e.support_[starts[j]:starts[j+1]]] = e.dual_coef_[i, starts[j]:starts[j+1]]
                f = (k@beta)[idx] + e.intercept_[pair]; margin = sign*f
                alpha = beta[idx]*sign
                bounds = np.full(len(idx), e.C)
                if class_weight == 'balanced':
                    counts = {c: int((y==c).sum()) for c in classes}
                    bounds *= np.array([len(y)/(len(classes)*counts[c]) for c in y[idx]])
                v = np.where(alpha <= 1e-10, np.maximum(1-margin, 0),
                    np.where(alpha >= bounds-1e-10, np.maximum(margin-1, 0), np.abs(margin-1)))
                norm = float(beta@k@beta)
                primal = .5*norm + np.dot(bounds, np.maximum(1-margin, 0))
                dual = alpha.sum()-.5*norm
                records.append(dict(classes=[int(classes[i]),int(classes[j])], kkt_max=float(v.max(initial=0)),
                    equality_residual=float(abs(beta.sum())), box_violation=float(np.maximum(np.maximum(-alpha,alpha-bounds),0).max(initial=0)),
                    primal=float(primal), dual=float(dual), gap=float(primal-dual)))
                pair += 1
    return dict(version=QUALITY_VERSION, threshold=tol, checks=records,
        accepted=all(r['kkt_max'] <= tol and r['equality_residual'] <= 1e-7*max(1,e.C) and r['box_violation'] <= 1e-7*max(1,e.C) for r in records))
