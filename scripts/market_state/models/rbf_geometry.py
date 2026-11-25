"""Train-fitted financial and macro coordinates for the weighted RBF kernel."""
import numpy as np
from scipy.spatial.distance import cdist

GEOMETRY_VERSION = 'rbf-block-total-variance-v1'
COMPACT_FIELDS = {'latest', 'change', 'vol_20obs', 'not_applicable', 'release_gap', 'missing'}
CLOCK_FIELDS = {'age_days', 'not_applicable', 'release_gap', 'missing'}


class BlockGeometry:
    def __init__(self, state):
        if state['version'] != GEOMETRY_VERSION:
            raise ValueError('Unknown fitted RBF geometry version')
        self.state = state

    @classmethod
    def fit(cls, X, lineage, representation, weight, *, macro_only=False):
        values = X.to_numpy(dtype='float64')
        means = values.mean(axis=0)
        variances = np.mean(np.square(values - means), axis=0)
        groups = {'financial': [], 'macro': []}
        duplicate_columns, constant_columns = [], []
        seen = set()
        for j, column in enumerate(X.columns):
            raw = column.removeprefix('missing__')
            group = lineage.get(raw)
            if raw.startswith('macro__') and group is None:
                raise ValueError('Missing sealed macro feature lineage: ' + raw)
            if macro_only and group is None:
                raise ValueError('Z-only geometry received a non-macro column: ' + raw)
            if group is not None:
                field = raw.rsplit('__', 1)[-1]
                include = (representation == 'full' or
                    representation == 'compact' and field in COMPACT_FIELDS or
                    representation == 'clock' and field in CLOCK_FIELDS)
                if not include:
                    continue
            if variances[j] == 0:
                constant_columns.append(column)
                continue
            if group is not None and representation != 'full':
                # Repeated flags for the same economic group should not count
                # several times in the training distance.
                signature = group, values[:, j].tobytes()
                if signature in seen:
                    duplicate_columns.append(column)
                    continue
                seen.add(signature)
            groups['financial' if group is None else 'macro'].append(j)
        if macro_only:
            if weight != 1. or not groups['macro']:
                raise ValueError('Z-only RBF needs a varying macro block and unit block weight')
        elif not groups['financial']:
            raise ValueError('Weighted RBF requires a varying financial block')
        blocks = {}
        for name, indices in groups.items():
            columns = X.columns[indices].tolist()
            blocks[name] = dict(indices=indices, columns=columns,
                groups=[lineage.get(c.removeprefix('missing__'), 'financial') for c in columns],
                center=means[indices].tolist(), q=float(variances[indices].sum()))
        return cls(dict(version=GEOMETRY_VERSION, input_columns=X.columns.tolist(),
            representation=representation, macro_weight=float(weight), blocks=blocks,
            duplicate_columns=duplicate_columns, constant_columns=constant_columns))

    def coordinates(self, X):
        if X.columns.tolist() != self.state['input_columns']:
            raise ValueError('RBF geometry input column order mismatch')
        values = X.to_numpy(dtype='float64')
        blocks = [self.state['blocks'][name] for name in ['financial', 'macro']]
        return tuple((values[:, b['indices']] - np.array(b['center'])) / np.sqrt(b['q'])
            if b['indices'] else np.empty((len(X), 0)) for b in blocks)

    def transform(self, X):
        market, macro = self.coordinates(X)
        weight = self.state['macro_weight']
        if weight == 0 or not macro.shape[1]:
            return np.ascontiguousarray(market)
        return np.ascontiguousarray(np.column_stack((market, np.sqrt(weight) * macro)))

    def compare(self, X, Xp, eta, legacy_gamma, *, max_train_rows=192):
        """Matched diagonals-excluded training and forward cross-kernel summaries."""
        positions = np.linspace(0, len(X) - 1, min(max_train_rows, len(X)), dtype=int)
        train = X.iloc[positions]
        left, right = self.coordinates(train), self.coordinates(Xp)
        weight = self.state['macro_weight']
        quantiles = [0., .01, .25, .5, .75, .99, 1.]

        def summary(q, a, b, mask):
            if not mask.any():
                return {'pairs': 0}
            m, z = [cdist(x, y, 'sqeuclidean')[mask] for x, y in zip(q, left)]
            legacy = legacy_gamma * cdist(a, b, 'sqeuclidean')[mask]
            exponent = eta * (m + weight * z)
            k, old = np.exp(-exponent), np.exp(-legacy)
            return dict(pairs=int(mask.sum()), financial_distance=np.quantile(m, quantiles).tolist(),
                macro_distance=np.quantile(z, quantiles).tolist(), exponent=np.quantile(exponent, quantiles).tolist(),
                legacy_exponent=np.quantile(legacy, quantiles).tolist(),
                kernel=np.quantile(k, quantiles).tolist(), legacy_kernel=np.quantile(old, quantiles).tolist(),
                legacy_kernel_rms_change=float(np.sqrt(np.mean(np.square(k - old)))),
                zero_weight_kernel_rms_change=float(np.sqrt(np.mean(np.square(k - np.exp(-eta * m))))),
                macro_mean_share=float((eta * weight * z).sum() / exponent.sum()) if exponent.sum() else 0.)

        return dict(gamma_base=1., gamma_factor=float(eta), gamma=float(eta),
            legacy_gamma_base=float(legacy_gamma / eta), legacy_gamma=float(legacy_gamma),
            train_positions=positions.tolist(), quantiles=quantiles,
            train_train=summary(left, train, train, ~np.eye(len(train), dtype=bool)),
            prediction_train=summary(right, Xp, train, np.ones((len(Xp), len(train)), dtype=bool)))
