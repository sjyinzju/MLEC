"""Model-independent, train-only semantic input adaptation (not label scaling)."""
import copy
import json
import re
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.utils.validation import check_is_fitted
from .common import digest
from .model_contract import CONTRACT_VERSION

PREPROCESSING_VERSION = 'semantic-inputs-v2'


def nominal(name):
    return name == 'current_state_id' or name.startswith('current_state_id_lag')


def input_diagnostics(values):
    a = np.asarray(values, dtype='float64')
    with np.errstate(over='ignore'):
        norm = np.square(a).sum(axis=1)
    if not np.isfinite(a).all() or not np.isfinite(norm).all():
        raise ValueError('Non-finite input or squared row norm')
    return dict(rows=len(a), features=a.shape[1], max_abs=float(np.abs(a).max(initial=0)),
        max_row_norm2=float(norm.max(initial=0)),
        # Diagnostic only: legitimate market extremes are never clipped or rejected.
        large_value_columns=np.flatnonzero(np.abs(a).max(axis=0, initial=0) > 1e4).tolist())


class FoldPreprocessor(TransformerMixin, BaseEstimator):
    def fit(self, X, y=None):
        if not isinstance(X, pd.DataFrame) or not X.columns.is_unique or not len(X):
            raise ValueError('Nonempty named unique feature columns required')
        self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        self.dtypes_ = X.dtypes.astype(str).to_dict()
        self.categorical_ = [c for c in X if nominal(c)]
        self.numeric_ = [c for c in X if c not in self.categorical_]
        n = X[self.numeric_].astype(float)
        if np.isinf(n.to_numpy()).any():
            raise ValueError('Infinite input feature')
        self.all_empty_ = [c for c in n if n[c].isna().all()]
        self.constant_ = [c for c in n if c not in self.all_empty_ and n[c].nunique(dropna=True) <= 1]
        self.feature_types_ = {}
        for c in self.numeric_:
            if re.fullmatch(r'current_state_prob_\d+(?:_lag\d+w)?', c):
                kind = 'probability'
            elif n[c].notna().any() and n[c].dropna().isin([0., 1.]).all():
                kind = 'binary'
            else:
                kind = 'continuous'
            self.feature_types_[c] = kind
        self.feature_types_.update({c: 'nominal' for c in self.categorical_})
        self.median_ = n.median().fillna(0.)
        for c in self.numeric_:
            if self.feature_types_[c] == 'binary':
                # A median of .5 would invent a third binary value. Tied modes
                # select zero, solely from the current training support.
                self.median_.loc[c] = float(n[c].mode(dropna=True).iloc[0])
        filled = n.fillna(self.median_)
        mean, variance = filled.mean(), filled.var(ddof=0)
        # StandardScaler's floating-point error bound, relative to each column's
        # own units: small-unit Amihud values are not "near zero" by fiat.
        eps = np.finfo('float64').eps
        bound = len(n) * eps * variance + (len(n) * mean * eps) ** 2
        self.near_constant_ = [c for c in n if c not in self.all_empty_ + self.constant_
            and self.feature_types_[c] == 'continuous' and variance[c] <= bound[c]]
        self.retained_ = [c for c in n if c not in self.all_empty_ + self.constant_ + self.near_constant_]
        self.center_ = pd.Series({c: float(mean[c]) if self.feature_types_[c] == 'continuous' else 0. for c in self.retained_}, dtype=float)
        self.scale_ = pd.Series({c: float(np.sqrt(variance[c])) if self.feature_types_[c] == 'continuous' else 1. for c in self.retained_}, dtype=float)
        self.median_ = self.median_.reindex(self.retained_)
        self.statistics_ = {c: dict(observed=int(n[c].notna().sum()), missing=int(n[c].isna().sum()),
            imputed_mean=float(mean[c]), imputed_variance=float(variance[c]),
            imputation='training_mode_low_tie' if self.feature_types_[c] == 'binary' else 'training_median',
            type=self.feature_types_[c], strategy='standardize' if self.feature_types_[c] == 'continuous' else 'identity') for c in self.numeric_}
        if not np.isfinite(self.scale_.to_numpy()).all() or (self.scale_ <= 0).any():
            raise ValueError('Invalid train input scale')
        self.categories_ = {c: sorted(X[c].dropna().unique().tolist()) for c in self.categorical_}
        if any(not np.isfinite(np.asarray(v, dtype=float)).all() for v in self.categories_.values()):
            raise ValueError('Non-finite nominal state')
        self._names()
        self.training_diagnostics_ = input_diagnostics(self.transform(X))
        self._schema()
        return self

    def _names(self):
        names = list(self.retained_) + ['missing__' + c for c in self.numeric_]
        for c, values in self.categories_.items():
            names += [c + '==' + str(v) for v in values] + [c + '==MISSING', c + '==UNSEEN']
        if len(names) != len(set(names)):
            raise ValueError('Encoded feature names collide')
        self.output_names_ = np.asarray(names, dtype=object)

    def transform(self, X):
        check_is_fitted(self, 'output_names_')
        if list(X.columns) != list(self.feature_names_in_):
            raise ValueError('Validation/test input column order differs from training')
        if X.dtypes.astype(str).to_dict() != self.dtypes_:
            raise ValueError('Input dtype differs from fitted schema')
        n = X[self.numeric_].astype(float)
        if np.isinf(n.to_numpy()).any():
            raise ValueError('Infinite input feature')
        if np.isinf(X[self.categorical_].to_numpy(float)).any():
            raise ValueError('Infinite nominal state')
        for c in (c for c in self.numeric_ if self.feature_types_[c] == 'probability'):
            observed = n[c].dropna()
            if not observed.between(0., 1.).all():
                raise ValueError('State probability outside [0,1]: ' + c)
        values = (n[self.retained_].fillna(self.median_) - self.center_) / self.scale_
        parts = [values.to_numpy(float), n.isna().to_numpy(float)]
        for c, categories in self.categories_.items():
            parts += [np.column_stack([X[c].eq(v).fillna(False).to_numpy(float) for v in categories] + [
                X[c].isna().to_numpy(float), (X[c].notna() & ~X[c].isin(categories)).to_numpy(float)])]
        result = np.concatenate(parts, axis=1)
        input_diagnostics(result)
        return result

    def get_feature_names_out(self, input_features=None):
        check_is_fitted(self, 'output_names_')
        return self.output_names_.copy()

    def subset(self, columns):
        """Exact restriction of univariate training statistics, without refitting."""
        check_is_fitted(self, 'output_names_')
        if len(columns) != len(set(columns)) or not set(columns) <= set(self.feature_names_in_):
            raise ValueError('Unknown or repeated subset column')
        p = copy.copy(self)
        p.feature_names_in_ = np.asarray(columns, dtype=object)
        p.dtypes_ = {c: self.dtypes_[c] for c in columns}
        for name in ['categorical_', 'numeric_', 'all_empty_', 'constant_', 'near_constant_', 'retained_']:
            setattr(p, name, [c for c in getattr(self, name) if c in columns])
        for name in ['median_', 'center_', 'scale_']:
            setattr(p, name, getattr(self, name).reindex(p.retained_))
        p.feature_types_ = {c: self.feature_types_[c] for c in columns}
        p.statistics_ = {c: self.statistics_[c] for c in p.numeric_}
        p.categories_ = {c: self.categories_[c] for c in p.categorical_}
        p._names()
        p.training_diagnostics_ = dict(source='parent_training_schema', schema_version=self.schema_['schema_version'])
        if hasattr(p, 'fit_context_'):
            del p.fit_context_
        p._schema()
        return p

    def _schema(self):
        self.schema_ = dict(contract_version=CONTRACT_VERSION, preprocessing_version=PREPROCESSING_VERSION,
            raw_columns=self.feature_names_in_.tolist(), raw_dtypes=self.dtypes_,
            output_columns=self.output_names_.tolist(), output_dtype='float64',
            categorical=self.categories_, all_empty=self.all_empty_, constant=self.constant_, near_constant=self.near_constant_,
            retained=self.retained_, median=self.median_.to_dict(), center=self.center_.to_dict(), scale=self.scale_.to_dict(),
            feature_types=self.feature_types_, training_statistics=self.statistics_,
            missing='continuous/probability training median; binary training mode (low tie); fixed missing indicators; nominal MISSING/UNSEEN',
            scaling='probability/binary identity; continuous train imputed mean/population STD; numerical constants dropped',
            constant_rule='var <= n*eps*var + (n*mean*eps)^2; all-empty/constant values dropped; indicators retained')
        self.refresh_schema_version()

    def refresh_schema_version(self):
        self.schema_.pop('schema_version', None)
        self.schema_['schema_version'] = digest(self.schema_)

    def save(self, path):
        check_is_fitted(self, 'output_names_')
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, path / 'preprocessor.joblib')
        (path / 'input_schema.json').write_text(json.dumps(self.schema_, ensure_ascii=False, indent=2), encoding='utf8')

    @classmethod
    def load(cls, path):
        path = Path(path)
        p = joblib.load(path / 'preprocessor.joblib')  # trusted local artifacts only
        schema = json.loads((path / 'input_schema.json').read_text(encoding='utf8'))
        if not isinstance(p, cls) or p.schema_ != schema or schema['contract_version'] != CONTRACT_VERSION or schema.get('preprocessing_version') != PREPROCESSING_VERSION:
            raise ValueError('Preprocessor/schema mismatch')
        if digest({k: v for k, v in schema.items() if k != 'schema_version'}) != schema['schema_version']:
            raise ValueError('Preprocessor schema identity mismatch')
        context = schema.get('fit_context')
        p._schema()
        if context is not None:
            p.schema_['fit_context'] = context
            p.refresh_schema_version()
        if p.schema_ != schema:
            raise ValueError('Preprocessor fitted statistics modified')
        return p
