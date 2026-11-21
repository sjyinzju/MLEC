"""RBF-SVC with training-only time calibration; seven shared-parameter RBF-SVRs."""
from dataclasses import asdict
from pathlib import Path
import json
import warnings
import sys
import joblib
import numpy as np
import pandas as pd
import sklearn
import scipy
from sklearn.svm import SVC, SVR
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits
from ..common import CORE, digest
from ..model_contract import (fit_context, key_hash, fit_inputs, transform_inputs, validate_model_input,
    classification_output, regression_output, validate_output, package_manifest)
from ..target_adapters import fit_targets, TargetAdapter
from ..preprocessing import FoldPreprocessor
from ..release import file_hash, code_hash
from . import capabilities
from .errors import FitFailure
from .calibration import TimeSigmoid, decision_columns
from .specifications import validate_parameters


def model_code_hash():
    return digest({p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob('*.py'))})


def libraries():
    return dict(python='.'.join(map(str, sys.version_info[:2])), sklearn=sklearn.__version__, scipy=scipy.__version__, numpy=np.__version__,
        pandas=pd.__version__, joblib=joblib.__version__)


def relative_gamma(X, factor):
    values = np.asarray(X, dtype='float64')
    if values.ndim != 2 or not values.shape[1] or not np.isfinite(values).all():
        raise ValueError('Gamma requires finite training inputs with at least one feature')
    variance = float(values.var())
    base = 1. / (values.shape[1] * variance) if variance > 0 else 1.
    gamma = base * factor
    if not np.isfinite(gamma) or gamma <= 0:
        raise FitFailure('Invalid training gamma scale', [])
    return float(gamma)


class RBFSVMAdapter:
    def __init__(self, *, task, preprocessor, target_adapter, training_keys, parameters,
                 seed, policy, threads=1, solver, calibration, training_service=None):
        if task not in ['classification', 'regression'] or threads < 1:
            raise ValueError('Two primary tasks and positive CPU threads required')
        validate_parameters('rbf_svm', task, parameters)
        if policy['single_class'] != 'error' or policy['missing_class'] not in ['error', 'zero_for_absent']:
            raise ValueError('Explicit class policy required')
        self.task, self.preprocessor, self.target_adapter = task, preprocessor, target_adapter
        self.training_keys, self.parameters = training_keys.copy(), dict(parameters)
        self.seed, self.policy, self.threads = int(seed), dict(policy), int(threads)
        self.solver, self.calibration = dict(solver), dict(calibration)
        self.training_service = training_service
        self.capabilities = capabilities('rbf_svm', task)
        self.target_adapter.check_context(self.preprocessor.fit_context_)
        self.diagnostics_, self.calibration_plan_ = [], []

    def estimator(self, maximum, gamma):
        p = self.parameters
        common = dict(kernel='rbf', C=p['C'], gamma=gamma, tol=p['tol'], max_iter=maximum,
            shrinking=self.solver['shrinking'], cache_size=self.solver['cache_size_mb'])
        if self.task == 'classification':
            return SVC(**common, probability=False, decision_function_shape='ovr',
                class_weight=self.policy['class_weight'], random_state=self.seed, break_ties=False)
        return SVR(**common, epsilon=p['epsilon'])

    def _solve(self, X, y, *, target, phase, block=None):
        gamma = relative_gamma(X, self.parameters['gamma_factor'])
        for attempt in range(self.policy['convergence_retries'] + 1):
            maximum = self.parameters['max_iter'] * self.policy['iteration_multiplier'] ** attempt
            estimator = self.estimator(maximum, gamma)
            record = dict(component='estimator', target=target, phase=phase, block_id=block, attempt=attempt + 1,
                gamma=gamma, gamma_factor=self.parameters['gamma_factor'], max_iter=maximum,
                rows=len(X), features=X.shape[1], warnings=[], converged=False)
            self.diagnostics_.append(record)
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                try:
                    estimator.fit(X, y)
                except BaseException as error:
                    record.update(error=type(error).__name__ + ': ' + str(error),
                        warnings=[dict(category=w.category.__name__, message=str(w.message)) for w in caught])
                    if not isinstance(error, Exception) or isinstance(error, (MemoryError, OSError)):
                        error.diagnostics = self.diagnostics_
                        raise
                    raise FitFailure('RBF solver failed: ' + target, self.diagnostics_) from error
            numerical = not all(np.isfinite(np.asarray(getattr(estimator, a))).all() for a in
                ['support_vectors_', 'dual_coef_', 'intercept_']) or any(issubclass(w.category, RuntimeWarning) for w in caught)
            convergence = int(estimator.fit_status_) != 0 or any(issubclass(w.category, ConvergenceWarning) for w in caught)
            record.update(numerical_failure=numerical, converged=not numerical and not convergence,
                warnings=[dict(category=w.category.__name__, message=str(w.message)) for w in caught],
                fit_status=int(estimator.fit_status_), n_iter=np.asarray(estimator.n_iter_).tolist(),
                support_vectors=int(len(estimator.support_)), n_support=np.asarray(estimator.n_support_).tolist())
            if numerical:
                raise FitFailure('Non-finite kernel solution or numerical warning', self.diagnostics_)
            if not convergence:
                return estimator
        raise FitFailure('RBF solver convergence retries exhausted', self.diagnostics_)

    def fit(self, X_train, y_train, context):
        self.__dict__.pop('model_version_', None)
        self.diagnostics_, self.calibration_plan_ = [], []
        self.calibrator_ = None
        validate_model_input(X_train, self.preprocessor.schema_, keys=self.training_keys)
        expected = asdict(context)
        expected.pop('training_target_hash')
        if expected != self.preprocessor.fit_context_ or key_hash(self.training_keys) != context.training_keys_hash:
            raise ValueError('Model fit differs from its input training context')
        self.target_adapter.check_context(context)
        if context.training_target_hash != self.target_adapter.context_['training_target_hash']:
            raise ValueError('Model/target training truth identity mismatch')
        self.fit_context_ = asdict(context)
        y = np.asarray(y_train)
        with threadpool_limits(limits=self.threads):
            if self.task == 'classification':
                if y.shape != (len(X_train),) or not np.isin(y, range(len(self.target_adapter.schema_['class_ids']))).all():
                    raise ValueError('One-dimensional internal hard classes required')
                if len(np.unique(y)) != len(self.target_adapter.schema_['class_ids']):
                    raise FitFailure('Time-calibrated SVC requires all dictionary classes in outer train', [])
                if self.training_service is None:
                    raise ValueError('Classification requires the bound raw training-only partition service')
                self.training_service.check_context(context)
                outer = self.training_service.outer_training()
                pd.testing.assert_frame_equal(X_train, transform_inputs(self.preprocessor, outer))
                np.testing.assert_array_equal(y, self.target_adapter.transform(outer.y))
                self.calibration_plan_ = self.training_service.validate_plan(self.calibration)
                scores, labels = [], []
                for block in self.calibration_plan_:
                    if block['status'] != 'ACCEPTED':
                        continue
                    train, val = self.training_service.partition(block)
                    # Start from RAW internal train, never sliced outer-transformed X.
                    pre, target = fit_inputs(train), fit_targets(train)
                    Xi, Xv = transform_inputs(pre, train), transform_inputs(pre, val)
                    estimator = self._solve(Xi, target.transform(train.y), target='classification', phase='internal', block=block['block_id'])
                    scores.append(decision_columns(estimator.decision_function(Xv), estimator.classes_, len(target.schema_['class_ids'])))
                    labels.append(target.transform(val.y))
                    block.update(preprocessing_version=pre.schema_['schema_version'], gamma=float(estimator._gamma),
                        latest_train_label=str(train.metadata.label_available_at.max()),
                        latest_validation_label=str(val.metadata.label_available_at.max()))
                calibrator = TimeSigmoid(self.calibration)
                try:
                    calibrator.fit(np.vstack(scores), np.concatenate(labels), list(range(len(self.target_adapter.schema_['class_ids']))))
                except FitFailure as error:
                    self.diagnostics_.extend(error.diagnostics)
                    raise FitFailure(str(error), self.diagnostics_) from error
                self.diagnostics_.extend(calibrator.diagnostics_)
                self.calibrator_ = calibrator
                # Refit final preprocessing on all mature outer training rows.
                final_pre = fit_inputs(outer)
                if final_pre.schema_ != self.preprocessor.schema_:
                    raise ValueError('Final full-train preprocessing identity changed')
                self.preprocessor = final_pre
                self.estimators_ = [self._solve(transform_inputs(final_pre, outer), y, target='classification', phase='final')]
            else:
                if y.shape != (len(X_train), 7) or not np.isfinite(y).all():
                    raise ValueError('Finite adapted seven-target matrix required')
                self.estimators_ = [self._solve(X_train, y[:, j], target=c, phase='final') for j, c in enumerate(CORE)]
        self.actual_gamma_ = [float(e._gamma) for e in self.estimators_]
        self.model_version_ = self._weight_identity()
        return self

    def _weight_identity(self):
        return digest(dict(fit=self.fit_context_, parameters=self.parameters, policy=self.policy, seed=self.seed,
            solver=self.solver, calibration=self.calibration, gamma=self.actual_gamma_,
            calibration_plan=self.calibration_plan_,
            calibrator=self.calibrator_.state() if self.calibrator_ is not None else None, weights=joblib.hash(self.estimators_)))

    def predict(self, X_predict, context):
        if not hasattr(self, 'model_version_'):
            raise ValueError('Estimator is not fitted')
        validate_model_input(X_predict, self.preprocessor.schema_, keys=context.keys)
        if context.model_version != self.model_version_ or context.model_id != 'rbf_svm':
            raise ValueError('Model family/weight identity mismatch')
        for name in ['fold_id', 'fit_cutoff', 'information_set', 'quality', 'versions']:
            if getattr(context, name) != self.fit_context_[name]:
                raise ValueError('Prediction context mismatch: ' + name)
        if len(context.keys) and (not context.keys.market_id.eq(self.fit_context_['market_id']).all() or
                not context.keys.asof_date.dt.to_period('M').astype(str).eq(context.fold_id).all()):
            raise ValueError('Prediction keys differ from fitted market/month')
        if context.preprocessing_version != self.preprocessor.schema_['schema_version'] or context.target_adapter_version != self.target_adapter.adapter_version_:
            raise ValueError('Model component identity mismatch')
        schema = self.target_adapter.schema_
        with threadpool_limits(limits=self.threads):
            if self.task == 'classification':
                e = self.estimators_[0]
                p = self.calibrator_.predict_proba(decision_columns(e.decision_function(X_predict), e.classes_, len(schema['class_ids'])))
                p = self.target_adapter.align_probabilities(p, list(range(len(schema['class_ids']))), missing_policy='error')
                output = classification_output(context, np.asarray(schema['class_ids'])[p.argmax(axis=1)], p, schema)
            else:
                values = np.column_stack([e.predict(X_predict) for e in self.estimators_])
                output = regression_output(context, self.target_adapter.inverse_transform(values), schema)
        return validate_output(output, context, task=self.task, schema=schema)

    def diagnostic_artifact(self):
        return dict(kernel='rbf', parameters=self.parameters, actual_gamma=self.actual_gamma_,
            solver=self.solver, calibration_rules=self.calibration if self.task == 'classification' else None,
            calibration_plan=self.calibration_plan_, diagnostics=self.diagnostics_)

    def save(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        self.preprocessor.save(directory / 'input')
        self.target_adapter.save(directory / 'target.json')
        self.training_keys.to_parquet(directory / 'training_keys.parquet', index=False)
        joblib.dump(self.estimators_, directory / 'estimators.joblib')
        calibrator = self.calibrator_.state() if self.calibrator_ else None
        (directory / 'calibrator.json').write_text(json.dumps(calibrator, indent=2, allow_nan=False), encoding='utf8')
        manifest = package_manifest(self.preprocessor, self.target_adapter, self.capabilities, model_version=self.model_version_)
        manifest.update(estimator_created=True, model_family='rbf_svm', task=self.task, parameters=self.parameters,
            seed=self.seed, policy=self.policy, threads=self.threads, backend='cpu', solver=self.solver,
            calibration=self.calibration, calibration_plan=self.calibration_plan_, actual_gamma=self.actual_gamma_,
            diagnostics=self.diagnostics_, full_fit_context=self.fit_context_, calibrator='calibrator.json',
            library_versions=libraries(), model_code_hash=model_code_hash(), interface_code_hash=code_hash())
        manifest['files'] = {p.relative_to(directory).as_posix(): file_hash(p) for p in sorted(directory.rglob('*')) if p.is_file()}
        manifest['content_hash'] = digest(manifest)
        (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf8')

    @classmethod
    def load(cls, directory):
        directory = Path(directory)
        m = json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
        expected = m.pop('content_hash')
        if digest(m) != expected:
            raise ValueError('Model package manifest modified')
        if m['model_family'] != 'rbf_svm' or m['library_versions'] != libraries() or m['model_code_hash'] != model_code_hash() or m['interface_code_hash'] != code_hash():
            raise ValueError('Model package code/dependency versions differ')
        for name, sha in m['files'].items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory.resolve()) or file_hash(path) != sha:
                raise ValueError('Model package component modified: ' + name)
        pre = FoldPreprocessor.load(directory / 'input')
        target = TargetAdapter.load(directory / 'target.json', context=pre.fit_context_)
        model = cls(task=m['task'], preprocessor=pre, target_adapter=target,
            training_keys=pd.read_parquet(directory / 'training_keys.parquet'), parameters=m['parameters'],
            seed=m['seed'], policy=m['policy'], threads=m['threads'], solver=m['solver'], calibration=m['calibration'])
        if pre.schema_ != m['input_schema'] or target.schema_ != m['target_schema'] or target.adapter_version_ != m['target_adapter_version']:
            raise ValueError('Model package schema mismatch')
        model.estimators_ = joblib.load(directory / 'estimators.joblib')
        state = json.loads((directory / 'calibrator.json').read_text(encoding='utf8'))
        model.calibrator_ = TimeSigmoid.from_state(state, m['calibration']) if state is not None else None
        if (model.task == 'classification') != (model.calibrator_ is not None):
            raise ValueError('Model calibration component missing/unexpected')
        model.fit_context_, model.diagnostics_ = m['full_fit_context'], m['diagnostics']
        model.calibration_plan_, model.actual_gamma_ = m['calibration_plan'], m['actual_gamma']
        model.model_version_ = model._weight_identity()
        if model.model_version_ != m['model_version'] or key_hash(model.training_keys) != model.fit_context_['training_keys_hash']:
            raise ValueError('Model package weights/training membership mismatch')
        return model
