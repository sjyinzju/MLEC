"""scikit-learn 1.8 CPU adapters. Construction/import never fits an estimator."""
from dataclasses import asdict
from pathlib import Path
import json
import warnings
import joblib
import sklearn
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, ElasticNet
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits
from ..common import CORE, digest
from ..model_contract import (fit_context, key_hash, validate_model_input, classification_output,
    regression_output, validate_output, package_manifest)
from ..preprocessing import FoldPreprocessor
from ..target_adapters import TargetAdapter
from ..release import file_hash, code_hash
from . import capabilities


class FitFailure(RuntimeError):
    def __init__(self, message, diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


class ElasticNetAdapter:
    def __init__(self, *, task, preprocessor, target_adapter, training_keys, parameters,
                 seed, policy, threads=1):
        if task not in ['classification', 'regression']:
            raise ValueError('Only the two primary tasks are supported')
        self.task = task
        self.capabilities = capabilities('elastic_net', task)
        self.preprocessor = preprocessor
        self.target_adapter = target_adapter
        self.training_keys = training_keys.copy()
        self.parameters = dict(parameters)
        self.seed, self.policy, self.threads = int(seed), dict(policy), int(threads)
        if threads < 1:
            raise ValueError('Positive CPU thread limit required')
        if policy['missing_class'] not in ['error', 'zero_for_absent'] or policy['single_class'] != 'error':
            raise ValueError('Explicit missing-class policy and single-class error required')
        if policy['class_weight'] not in [None, 'balanced']:
            raise ValueError('Supported class weights: null or balanced')
        self.target_adapter.check_context(self.preprocessor.fit_context_)
        self.diagnostics_ = []

    def estimator(self, max_iter):
        p = self.parameters
        if self.task == 'classification':
            # In 1.8 l1_ratio specifies the regularizer; penalty and n_jobs are deprecated.
            return LogisticRegression(solver='saga', C=p['C'], l1_ratio=p['l1_ratio'],
                tol=p['tol'], max_iter=max_iter, random_state=self.seed,
                class_weight=self.policy['class_weight'])
        return ElasticNet(alpha=p['alpha'], l1_ratio=p['l1_ratio'], tol=p['tol'],
            max_iter=max_iter, selection='cyclic', random_state=self.seed)

    def fit(self, X_train, y_train, context):
        self.__dict__.pop('model_version_', None)
        self.diagnostics_ = []
        validate_model_input(X_train, self.preprocessor.schema_, keys=self.training_keys)
        expected = dict(asdict(context))
        expected.pop('training_target_hash')
        if expected != self.preprocessor.fit_context_ or key_hash(self.training_keys) != context.training_keys_hash:
            raise ValueError('Model fit context differs from bound input training context')
        self.target_adapter.check_context(context)
        if context.training_target_hash != self.target_adapter.context_['training_target_hash']:
            raise ValueError('Model/target training truth identity mismatch')
        self.fit_context_ = asdict(context)
        y = np.asarray(y_train)
        if self.task == 'classification':
            if y.shape != (len(X_train),) or not np.isin(y, range(len(self.target_adapter.schema_['class_ids']))).all():
                raise ValueError('One-dimensional internal hard classes required')
            if len(np.unique(y)) < 2:
                raise FitFailure('Single-class training is forbidden', [])
            if self.target_adapter.parameters_['missing_classes'] and self.policy['missing_class'] == 'error':
                raise FitFailure('Dictionary classes absent from training', [])
            targets = [('classification', y)]
        else:
            if y.shape != (len(X_train), 7) or not np.isfinite(y).all():
                raise ValueError('Finite adapted seven-target matrix required')
            targets = [(c, y[:, j]) for j, c in enumerate(CORE)]
        self.estimators_ = []
        with threadpool_limits(limits=self.threads):
            for target, values in targets:
                fitted = None
                for attempt in range(self.policy['convergence_retries'] + 1):
                    maximum = self.parameters['max_iter'] * self.policy['iteration_multiplier'] ** attempt
                    estimator = self.estimator(maximum)
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter('always')
                        try:
                            estimator.fit(X_train, values)
                        except Exception as error:
                            self.diagnostics_.append(dict(target=target, attempt=attempt + 1,
                                max_iter=maximum, n_iter=None, dual_gap=[], nonzero=None, converged=False,
                                warnings=[{'category': w.category.__name__, 'message': str(w.message)} for w in caught],
                                error=type(error).__name__ + ': ' + str(error)))
                            raise FitFailure('Estimator fit failed for ' + target + ': ' + str(error), self.diagnostics_) from error
                    warning_records = [{'category': w.category.__name__, 'message': str(w.message)} for w in caught]
                    nonfinite = not (np.isfinite(estimator.coef_).all() and np.isfinite(estimator.intercept_).all()
                        and np.isfinite(np.asarray(getattr(estimator, 'dual_gap_', []))).all())
                    convergence = any(issubclass(w.category, ConvergenceWarning) for w in caught)
                    numerical = nonfinite or any(issubclass(w.category, RuntimeWarning) for w in caught)
                    self.diagnostics_.append(dict(target=target, attempt=attempt + 1, max_iter=maximum,
                        n_iter=np.asarray(estimator.n_iter_).tolist(),
                        dual_gap=np.where(np.isfinite(np.asarray(getattr(estimator, 'dual_gap_', []))),
                            np.asarray(getattr(estimator, 'dual_gap_', [])), None).tolist(), numerical_failure=numerical,
                        warnings=warning_records, converged=not convergence and not numerical,
                        nonzero=int(np.count_nonzero(estimator.coef_))))
                    if numerical:
                        raise FitFailure('Non-finite coefficients or numerical warning: ' + target, self.diagnostics_)
                    if not convergence:
                        fitted = estimator
                        break
                if fitted is None:
                    raise FitFailure('Convergence retries exhausted: ' + target, self.diagnostics_)
                self.estimators_.append(fitted)
        self.model_version_ = digest(dict(fit=self.fit_context_, parameters=self.parameters,
            seed=self.seed, weights=joblib.hash(self.estimators_), policy=self.policy))
        return self

    def predict(self, X_predict, context):
        if not hasattr(self, 'model_version_'):
            raise ValueError('Estimator is not fitted')
        validate_model_input(X_predict, self.preprocessor.schema_, keys=context.keys)
        if context.model_version != self.model_version_:
            raise ValueError('Model weight identity mismatch')
        if context.model_id != 'elastic_net':
            raise ValueError('Model family identity mismatch')
        for key in ['fold_id', 'fit_cutoff', 'information_set', 'quality', 'versions']:
            if getattr(context, key) != self.fit_context_[key]:
                raise ValueError('Model prediction context mismatch: ' + key)
        if len(context.keys) and (not context.keys.market_id.eq(self.fit_context_['market_id']).all() or
                not context.keys.asof_date.dt.to_period('M').astype(str).eq(context.fold_id).all()):
            raise ValueError('Prediction keys differ from model market/month')
        if context.preprocessing_version != self.preprocessor.schema_['schema_version'] or context.target_adapter_version != self.target_adapter.adapter_version_:
            raise ValueError('Model component identity mismatch')
        schema = self.target_adapter.schema_
        with threadpool_limits(limits=self.threads):
            if self.task == 'classification':
                estimator = self.estimators_[0]
                p = self.target_adapter.align_probabilities(estimator.predict_proba(X_predict),
                    estimator.classes_, missing_policy=self.policy['missing_class'])
                output = classification_output(context, np.asarray(schema['class_ids'])[p.argmax(axis=1)], p, schema)
            else:
                values = np.column_stack([e.predict(X_predict) for e in self.estimators_])
                output = regression_output(context, self.target_adapter.inverse_transform(values), schema)
        return validate_output(output, context, task=self.task, schema=schema)

    def coefficients(self):
        rows = []
        names = self.preprocessor.schema_['output_columns']
        for j, estimator in enumerate(self.estimators_):
            coefficients = np.atleast_2d(estimator.coef_)
            labels = estimator.classes_.tolist() if self.task == 'classification' else [CORE[j]]
            if len(coefficients) == 1 and len(labels) == 2:
                labels = [labels[1]]  # sklearn binary log-odds parameterization
            for target, weights, intercept in zip(labels, coefficients, np.atleast_1d(estimator.intercept_)):
                for feature, coefficient in zip(names + ['(intercept)'], list(weights) + [intercept]):
                    rows.append(dict(target=str(target), feature=feature, coefficient=float(coefficient),
                        fold_id=self.fit_context_['fold_id'], market_id=self.fit_context_['market_id'],
                        information_set=self.fit_context_['information_set'], seed=self.seed,
                        interpretation='penalized predictive coefficient; not a causal effect'))
        return pd.DataFrame(rows)

    def save(self, directory):
        """Caller stages this directory atomically. Load trusted local artifacts only."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        self.preprocessor.save(directory / 'input')
        self.target_adapter.save(directory / 'target.json')
        self.training_keys.to_parquet(directory / 'training_keys.parquet', index=False)
        joblib.dump(self.estimators_, directory / 'estimators.joblib')
        self.coefficients().to_csv(directory / 'coefficients.csv', index=False)
        manifest = package_manifest(self.preprocessor, self.target_adapter, self.capabilities,
            model_version=self.model_version_)
        manifest.update(estimator_created=True, task=self.task, parameters=self.parameters, seed=self.seed,
            policy=self.policy, threads=self.threads, diagnostics=self.diagnostics_, full_fit_context=self.fit_context_,
            calibrator=None, backend='cpu', model_family='elastic_net')
        manifest.update(library_versions=dict(sklearn=sklearn.__version__, numpy=np.__version__,
            pandas=pd.__version__, joblib=joblib.__version__), adapter_code_hash=file_hash(__file__),
            interface_code_hash=code_hash())
        manifest['files'] = {p.relative_to(directory).as_posix(): file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()}
        manifest['content_hash'] = digest(manifest)
        (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf8')

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
        expected = manifest.pop('content_hash')
        if digest(manifest) != expected:
            raise ValueError('Model package manifest modified')
        if manifest['library_versions'] != dict(sklearn=sklearn.__version__, numpy=np.__version__,
                pandas=pd.__version__, joblib=joblib.__version__) or manifest['adapter_code_hash'] != file_hash(__file__) or manifest['interface_code_hash'] != code_hash():
            raise ValueError('Model package code/dependency versions differ')
        for name, sha in manifest['files'].items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory.resolve()) or file_hash(path) != sha:
                raise ValueError('Model package component modified: ' + name)
        pre = FoldPreprocessor.load(directory / 'input')
        target = TargetAdapter.load(directory / 'target.json', context=pre.fit_context_)
        model = cls(task=manifest['task'], preprocessor=pre, target_adapter=target,
            training_keys=pd.read_parquet(directory / 'training_keys.parquet'), parameters=manifest['parameters'],
            seed=manifest['seed'], policy=manifest['policy'], threads=manifest['threads'])
        if pre.schema_ != manifest['input_schema'] or target.adapter_version_ != manifest['target_adapter_version']:
            raise ValueError('Model package schema mismatch')
        model.estimators_ = joblib.load(directory / 'estimators.joblib')
        model.fit_context_, model.diagnostics_ = manifest['full_fit_context'], manifest['diagnostics']
        model.model_version_ = digest(dict(fit=model.fit_context_, parameters=model.parameters,
            seed=model.seed, weights=joblib.hash(model.estimators_), policy=model.policy))
        if model.model_version_ != manifest['model_version']:
            raise ValueError('Model package weights mismatch')
        return model
