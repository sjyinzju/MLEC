"""RBF-SVC with time calibration and seven independent RBF-SVRs."""
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
import time
from scipy.special import softmax
from scipy.spatial.distance import cdist
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
from .calibration import TimeSigmoid, TimeShrinkage, decision_columns
from .rbf_geometry import BlockGeometry
from .specifications import validate_parameters
from .svm_quality import weight_hash, solution_quality, QUALITY_VERSION, array_state


def model_code_hash():
    return digest({p.name: file_hash(p) for p in sorted(Path(__file__).parent.glob('*.py'))})


def libraries():
    return dict(python='.'.join(map(str, sys.version_info[:2])), sklearn=sklearn.__version__, scipy=scipy.__version__, numpy=np.__version__,
        pandas=pd.__version__, joblib=joblib.__version__)


def relative_gamma(X, factor):
    values = np.asarray(X, dtype='float64')
    if values.ndim != 2 or not values.shape[1] or not np.isfinite(values).all():
        raise ValueError('Gamma requires finite training inputs with at least one feature')
    if not np.isfinite(factor) or factor <= 0 or not len(values):
        raise ValueError('Positive finite gamma factor and nonempty training rows required')
    # Scaling before variance avoids overflow/underflow in finite extreme inputs.
    maximum = float(np.max(np.abs(values)))
    variance = float((values / maximum).var()) if maximum else 0.
    base = ((1. / values.shape[1]) / variance / maximum / maximum) if variance > 0 else 1.
    gamma = base * factor
    if not np.isfinite(gamma) or gamma <= 0:
        raise FitFailure('Invalid training gamma scale', [])
    return float(gamma)


class RBFSVMAdapter:
    def __init__(self, *, task, preprocessor, target_adapter, training_keys, parameters,
                 seed, policy, threads=1, solver, calibration, training_service=None,
                 macro_lineage=None, oof_cache=None):
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
        self.macro_lineage = dict(macro_lineage or {})
        self.oof_cache = oof_cache
        self.geometry_ = None
        self.capabilities = capabilities('rbf_svm', task)
        self.target_adapter.check_context(self.preprocessor.fit_context_)
        self.diagnostics_, self.calibration_plan_ = [], []

    def estimator(self, maximum, gamma, target=None):
        p = self.parameters
        fitted = p.get('target_parameters', {}).get(target, p)
        common = dict(kernel='rbf', C=fitted['C'], gamma=gamma, tol=p['tol'], max_iter=maximum,
            shrinking=self.solver['shrinking'], cache_size=self.solver['cache_size_mb'])
        if self.task == 'classification':
            return SVC(**common, probability=False, decision_function_shape='ovr',
                class_weight=self.class_weight, random_state=self.seed, break_ties=False)
        return SVR(**common, epsilon=fitted['epsilon'])

    @property
    def class_weight(self):
        return self.parameters.get('class_weight', self.policy['class_weight'])

    @property
    def weighted(self):
        return 'geometry_version' in self.parameters

    def _geometry(self, X):
        return BlockGeometry.fit(X, self.macro_lineage, self.parameters['representation'], self.parameters['macro_weight'])

    def _solve(self, X, y, *, target, phase, block=None, kernel=None):
        factor = self.parameters['gamma_factor']
        gamma = factor if self.weighted else relative_gamma(X, factor)
        for attempt in range(self.policy['convergence_retries'] + 1):
            maximum = self.parameters['max_iter'] * self.policy['iteration_multiplier'] ** attempt
            estimator = self.estimator(maximum, gamma, target) if self.weighted else self.estimator(maximum, gamma)
            record = dict(component='estimator', target=target, phase=phase, block_id=block, attempt=attempt + 1,
                gamma=gamma, gamma_base=gamma / factor, gamma_factor=factor, max_iter=maximum,
                rows=len(X), features=X.shape[1], warnings=[], converged=False)
            self.diagnostics_.append(record)
            started = time.perf_counter()
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                try:
                    estimator.fit(X, y)
                except BaseException as error:
                    record.update(error=type(error).__name__ + ': ' + str(error),
                        elapsed_seconds=time.perf_counter()-started,
                        warnings=[dict(category=w.category.__name__, message=str(w.message)) for w in caught])
                    if not isinstance(error, Exception) or isinstance(error, (MemoryError, OSError)):
                        error.diagnostics = self.diagnostics_
                        raise
                    raise FitFailure('RBF solver failed: ' + target, self.diagnostics_) from error
            numerical = not all(np.isfinite(np.asarray(getattr(estimator, a))).all() for a in
                ['support_vectors_', 'dual_coef_', 'intercept_']) or any(issubclass(w.category, RuntimeWarning) for w in caught)
            convergence = int(estimator.fit_status_) != 0 or any(issubclass(w.category, ConvergenceWarning) for w in caught)
            record.update(numerical_failure=numerical, converged=not numerical and not convergence,
                elapsed_seconds=time.perf_counter()-started,
                warnings=[dict(category=w.category.__name__, message=str(w.message)) for w in caught],
                fit_status=int(estimator.fit_status_), n_iter=np.asarray(estimator.n_iter_).tolist(),
                support_vectors=int(len(estimator.support_)), n_support=np.asarray(estimator.n_support_).tolist())
            if not numerical and not convergence and hasattr(estimator, 'get_params'):
                record['quality'] = solution_quality(estimator, X, y, class_weight=self.class_weight, kernel=kernel)
                record['converged'] = record['quality']['accepted']
                if not record['quality']['accepted']:
                    raise FitFailure('Independent LIBSVM KKT check failed', self.diagnostics_)
            if numerical:
                raise FitFailure('Non-finite kernel solution or numerical warning', self.diagnostics_)
            if not convergence:
                return estimator
        raise FitFailure('RBF solver convergence retries exhausted', self.diagnostics_)

    def _time_oof(self, block, class_count):
        cache = self.oof_cache if self.weighted else None
        if cache is not None:
            key = (self.oof_namespace_, block['training_keys_hash'], block['validation_keys_hash'], block['fit_cutoff'])
            if key in cache:
                cache.move_to_end(key)
                self.oof_cache_hits_ += 1
                return cache[key]
        data = self.training_service.prepare_block(block)
        xi, xv = data['X'], data['X_validation']
        metadata = dict(data['metadata'])
        if self.weighted:
            geometry = self._geometry(xi)
            metadata.update(geometry_version=geometry.state['version'], geometry_hash=digest(geometry.state),
                block_q={name: v['q'] for name, v in geometry.state['blocks'].items()})
            metadata.pop('preprocessing_version')
            xi, xv = geometry.transform(xi), geometry.transform(xv)
        estimator = self._solve(xi, data['y'], target='classification', phase='internal', block=block['block_id'])
        scores = decision_columns(estimator.decision_function(xv), estimator.classes_, class_count)
        result = (scores, data['y_validation'], data['validation_keys'], data['validation_maturity'],
            dict(metadata, gamma=float(estimator._gamma)))
        if cache is not None:
            cache[key] = result
            if len(cache) > 3072:
                cache.popitem(last=False)
        return result

    def _new_calibrator(self):
        if self.parameters.get('calibrator') == 'shrinkage':
            return TimeShrinkage(self.calibration['shrinkage'])
        return TimeSigmoid(self.calibration)

    def _scores(self, X):
        estimator = self.estimators_[0]
        return decision_columns(estimator.decision_function(X), estimator.classes_,
            len(self.target_adapter.schema_['class_ids']))

    def _score_frame(self, keys, X_scores, role):
        frame = keys.copy()
        frame['score_role'] = role
        calibrated = self.calibrator_.predict_proba(X_scores)
        reference = softmax(X_scores, axis=1)
        for j, c in enumerate(self.target_adapter.schema_['class_ids']):
            frame['decision_' + str(c)] = X_scores[:, j]
            frame['score_softmax_' + str(c)] = reference[:, j]
            frame['calibrated_' + str(c)] = calibrated[:, j]
        return frame

    def fit(self, X_train, y_train, context):
        self.__dict__.pop('model_version_', None)
        self.diagnostics_, self.calibration_plan_ = [], []
        self.calibrator_ = self.geometry_ = None
        self.oof_cache_hits_ = 0
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
            X_fit = X_train
            if self.weighted:
                self.geometry_ = self._geometry(X_train)
                X_fit = self.geometry_.transform(X_train)
            if self.task == 'classification':
                if y.shape != (len(X_train),) or not np.isin(y, range(len(self.target_adapter.schema_['class_ids']))).all():
                    raise ValueError('One-dimensional internal hard classes required')
                if len(np.unique(y)) != len(self.target_adapter.schema_['class_ids']):
                    raise FitFailure('Time-calibrated SVC requires all dictionary classes in outer train', [])
                if self.training_service is None:
                    raise ValueError('Classification requires the bound raw training-only partition service')
                self.training_service.check_context(context)
                if self.weighted:
                    self.training_service.verify_outer_inputs(X_train, y, self.preprocessor, self.target_adapter)
                    self.oof_namespace_ = digest(dict(data=context.versions, quality=context.quality,
                        input_columns=self.preprocessor.schema_['raw_columns'], lineage=self.macro_lineage,
                        solver=self.solver, policy=self.policy, seed=self.seed,
                        parameters={k: v for k, v in self.parameters.items() if k != 'calibrator'}))
                else:
                    outer = self.training_service.outer_training()
                    pd.testing.assert_frame_equal(X_train, transform_inputs(self.preprocessor, outer))
                    np.testing.assert_array_equal(y, self.target_adapter.transform(outer.y))
                self.calibration_plan_ = self.training_service.validate_plan(self.calibration)
                scores, labels, validation_keys, validation_maturity, blocks = [], [], [], [], []
                for block in self.calibration_plan_:
                    if block['status'] != 'ACCEPTED':
                        continue
                    raw, label, keys, maturity, metadata = self._time_oof(block, len(self.target_adapter.schema_['class_ids']))
                    scores.append(raw)
                    labels.append(label)
                    validation_keys.append(keys)
                    validation_maturity.append(maturity)
                    blocks.extend([block['block_id']] * len(keys))
                    block.update(metadata)
                calibrator = self._new_calibrator()
                oof_scores,oof_y=np.vstack(scores),np.concatenate(labels)
                self.oof_diagnostics_=dict(score_hash=array_state(oof_scores),label_hash=array_state(oof_y),
                    class_counts=np.bincount(oof_y,minlength=len(self.target_adapter.schema_['class_ids'])).tolist(),
                    score_mean=oof_scores.mean(axis=0).tolist(),score_std=oof_scores.std(axis=0).tolist(),
                    score_quantiles=np.quantile(oof_scores,[0,.25,.5,.75,1],axis=0).tolist(),
                    semantics='sklearn OVO votes plus bounded confidence mapped to OVR; not independent hyperplane distances')
                try:
                    calibrator.fit(oof_scores, oof_y, list(range(len(self.target_adapter.schema_['class_ids']))))
                except FitFailure as error:
                    self.diagnostics_.extend(error.diagnostics)
                    raise FitFailure(str(error), self.diagnostics_) from error
                self.diagnostics_.extend(calibrator.diagnostics_)
                self.calibrator_ = calibrator
                if self.weighted:
                    self.oof_frame_ = self._score_frame(pd.concat(validation_keys, ignore_index=True),
                        oof_scores, 'TIME_OOF_CALIBRATOR_TRAIN')
                    self.oof_frame_['inner_block'] = blocks
                    self.oof_frame_['label_available_at'] = pd.concat(validation_maturity, ignore_index=True)
                    self.oof_frame_['future_state_id'] = np.asarray(self.target_adapter.schema_['class_ids'])[oof_y]
                else:
                    # Preserve the historical solver's independent outer reprojection.
                    final_pre = fit_inputs(outer)
                    if final_pre.schema_ != self.preprocessor.schema_:
                        raise ValueError('Final full-train preprocessing identity changed')
                    self.preprocessor = final_pre
                    X_fit = transform_inputs(final_pre, outer)
                self.estimators_ = [self._solve(X_fit, y, target='classification', phase='final')]
                if self.weighted:
                    train_scores = self._scores(X_fit)
                    self.oof_diagnostics_.update(outer_train_score_mean=train_scores.mean(axis=0).tolist(),
                        outer_train_score_std=train_scores.std(axis=0).tolist(),
                        outer_train_class_counts=np.bincount(y, minlength=oof_scores.shape[1]).tolist())
            else:
                if y.shape != (len(X_train), 7) or not np.isfinite(y).all():
                    raise ValueError('Finite adapted seven-target matrix required')
                kernel = np.exp(-self.parameters['gamma_factor'] * cdist(X_fit, X_fit, 'sqeuclidean')) if self.weighted else None
                self.estimators_ = [self._solve(X_fit, y[:, j], target=c, phase='final', kernel=kernel) for j, c in enumerate(CORE)]
                if self.weighted:
                    fitted = np.column_stack([e.predict(X_fit) for e in self.estimators_])
                    original = self.target_adapter.inverse_transform(fitted).to_numpy()
                    truth = self.target_adapter.inverse_transform(y).to_numpy()
                    self.training_metrics_ = dict(zip(CORE, [dict(
                        rmse=float(np.sqrt(np.mean(np.square(a - b)))), prediction_std=float(a.std()),
                        observed_std=float(b.std()), correlation=float(np.corrcoef(a, b)[0, 1]) if a.std() and b.std() else None)
                        for a, b in zip(original.T, truth.T)]))
        self.actual_gamma_ = [float(e._gamma) for e in self.estimators_]
        self.model_version_ = self._weight_identity()
        return self

    def _weight_identity(self):
        return digest(dict(fit=self.fit_context_, parameters=self.parameters, policy=self.policy, seed=self.seed,
            solver=self.solver, calibration=self.calibration, gamma=self.actual_gamma_,
            calibration_plan=self.calibration_plan_,
            input_schema=self.preprocessor.schema_['schema_version'], target_adapter=self.target_adapter.adapter_version_,
            quality_version=QUALITY_VERSION, geometry=self.geometry_.state if self.geometry_ else None,
            calibrator=dict(rules=self.calibrator_.rules, parameters=self.calibrator_.parameters_) if self.calibrator_ is not None else None,
            weights=weight_hash(self.estimators_)))

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
        X_fit = self.geometry_.transform(X_predict) if self.geometry_ else X_predict
        with threadpool_limits(limits=self.threads):
            if self.task == 'classification':
                p = self.calibrator_.predict_proba(self._scores(X_fit)) if len(X_fit) else np.empty((0, len(schema['class_ids'])))
                p = self.target_adapter.align_probabilities(p, list(range(len(schema['class_ids']))), missing_policy='error')
                output = classification_output(context, np.asarray(schema['class_ids'])[p.argmax(axis=1)], p, schema)
            else:
                values = np.column_stack([e.predict(X_fit) for e in self.estimators_]) if len(X_fit) else np.empty((0, len(CORE)))
                output = regression_output(context, self.target_adapter.inverse_transform(values), schema)
        return validate_output(output, context, task=self.task, schema=schema)

    def probability_evidence(self, Xp, keys):
        if self.task != 'classification' or not self.geometry_:
            return None
        scores = self._scores(self.geometry_.transform(Xp)) if len(Xp) else np.empty((0, len(self.target_adapter.schema_['class_ids'])))
        prediction = self._score_frame(keys, scores, 'OUTER_PREDICTION')
        return pd.concat([self.oof_frame_, prediction], ignore_index=True)

    def diagnostic_artifact(self, X=None, Xp=None, *, full_kernel=False):
        geometry = self.geometry_.state if self.geometry_ else None
        return dict(kernel='rbf', parameters=self.parameters, actual_gamma=self.actual_gamma_,
            oof=getattr(self,'oof_diagnostics_',None),
            cross_month_oof_cache_hits=self.oof_cache_hits_,
            geometry=dict(version=geometry['version'], hash=digest(geometry),
                blocks={k: dict(q=b['q'], features=len(b['columns'])) for k, b in geometry['blocks'].items()},
                constants=len(geometry['constant_columns']), duplicate_macro=len(geometry['duplicate_columns'])) if geometry else None,
            matched_kernel=self.geometry_.compare(X, Xp, self.actual_gamma_[0],
                relative_gamma(X, self.parameters['gamma_factor']), max_train_rows=len(X) if full_kernel else 80)
                if self.geometry_ and X is not None else None,
            training_metrics=getattr(self, 'training_metrics_', None),
            inner_cache=dict(hits=self.training_service.cache_hits, misses=self.training_service.cache_misses,
                bytes=self.training_service.cache_bytes, limit=self.training_service.cache_limit) if self.training_service else None,
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
            oof=getattr(self,'oof_diagnostics_',None),
            geometry=self.geometry_.state if self.geometry_ else None,
            training_metrics=getattr(self, 'training_metrics_', None),
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
        if state is not None:
            calibrator = model._new_calibrator()
            model.calibrator_ = type(calibrator).from_state(state, calibrator.rules)
        else:
            model.calibrator_ = None
        if (model.task == 'classification') != (model.calibrator_ is not None):
            raise ValueError('Model calibration component missing/unexpected')
        model.fit_context_, model.diagnostics_ = m['full_fit_context'], m['diagnostics']
        model.calibration_plan_, model.actual_gamma_ = m['calibration_plan'], m['actual_gamma']
        model.oof_diagnostics_=m.get('oof')
        model.geometry_ = BlockGeometry(m['geometry']) if m.get('geometry') is not None else None
        model.oof_cache_hits_ = 0
        model.training_metrics_ = m.get('training_metrics')
        model.model_version_ = model._weight_identity()
        if model.model_version_ != m['model_version'] or key_hash(model.training_keys) != model.fit_context_['training_keys_hash']:
            raise ValueError('Model package weights/training membership mismatch')
        return model
