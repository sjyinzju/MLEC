"""scikit-learn 1.8 CPU adapters. Construction/import never fits an estimator."""
from dataclasses import asdict
from pathlib import Path
import json
import warnings
import time
import joblib
import sklearn
import scipy
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, ElasticNet, LassoLars
from sklearn.exceptions import ConvergenceWarning
from threadpoolctl import threadpool_limits
from ..common import CORE, digest
from ..model_contract import (fit_context, key_hash, validate_model_input, classification_output,
    regression_output, validate_output, package_manifest)
from ..preprocessing import FoldPreprocessor
from ..target_adapters import TargetAdapter
from ..release import file_hash, code_hash
from . import capabilities
from .errors import FitFailure
from .elastic_quality import (classification_quality, regression_quality, certify_zero_slopes,
    weight_hash, QUALITY_VERSION, elastic_dual_state)
from ..preprocessing import input_diagnostics


def regression_geometry(X, alpha, l1_ratio):
    """Exact centered Elastic Net -> augmented Lasso, in original X coordinates."""
    x = np.asarray(X, dtype='float64')
    mean = x.mean(axis=0)
    centered = x - mean
    ridge = len(x) * alpha * (1. - l1_ratio)
    augmented = np.vstack([centered, np.sqrt(ridge) * np.eye(x.shape[1])]) if ridge > 0 else centered
    gram = centered.T @ centered
    gram.flat[::len(gram)+1] += ridge
    return dict(mean=mean, augmented=augmented, gram=gram, rows=len(x),
        alpha=alpha, l1_ratio=l1_ratio)


class AugmentedLarsElasticNet(ElasticNet):
    """Exact objective mapping, with independently certified dual refinement."""
    solver_name = 'exact_elastic_net_via_augmented_lasso_lars'

    def polish(self, geometry, values):
        """Bounded dual refinement without changing the primal objective.

        With L2, semismooth Newton returns the conjugate gradient w, whose gap
        is ||n*theta + Xc*w - yc||^2/(2*n). Pure L1 uses a constrained dual QP
        and recovers w from multipliers. Neither path uses scoring or test Y.
        """
        n = len(values)
        xc, yc = geometry['augmented'][:n], values-values.mean()
        l1, l2 = self.alpha*self.l1_ratio, self.alpha*(1.-self.l1_ratio)
        if l2 == 0.:
            # Pure L1: project yc/n onto |Xc.T theta| <= l1, sum(theta)=0.
            # SLSQP multipliers recover w in the ORIGINAL feature coordinates.
            initial = (yc-xc@self.coef_)/n
            initial -= initial.mean()
            norm = float(np.abs(xc.T@initial).max(initial=0.))
            initial *= min(1.,l1/norm) if norm else 1.
            jacobian = np.vstack([-xc.T,xc.T])
            result = minimize(lambda t: .5*n*np.dot(t,t)-np.dot(yc,t), initial,
                jac=lambda t:n*t-yc, method='SLSQP',
                constraints=[dict(type='eq',fun=lambda t:np.sum(t),jac=lambda t:np.ones(n)),
                    dict(type='ineq',fun=lambda t:np.r_[l1-xc.T@t,l1+xc.T@t],jac=lambda t:jacobian)],
                options=dict(maxiter=min(2000,self.max_iter),ftol=1e-12,disp=False))
            multipliers = np.asarray(result.multipliers)[1:]
            if multipliers.shape != (2*xc.shape[1],):
                raise ValueError('Unexpected dual QP multiplier shape')
            w = multipliers[:xc.shape[1]]-multipliers[xc.shape[1]:]
            theta = result.x-result.x.mean()
            norm = float(np.abs(xc.T@theta).max(initial=0.))
            theta *= min(1.,l1/norm)*(1.-8.*np.finfo(float).eps) if norm else 1.
            residual_gradient = n*theta+xc@w-yc
            self.coef_, self.intercept_ = w, float(values.mean()-geometry['mean']@w)
            self.dual_certificate_ = theta
            self.dual_gap_ = float(np.dot(residual_gradient,residual_gradient)/(2.*n)+l1*np.abs(w).sum()-np.dot(w,xc.T@theta))
            self.solver_mapping_.update(dual_qp_steps=int(result.nit),dual_qp_limit=min(2000,self.max_iter),
                dual_qp_status=int(result.status),dual_qp_message=str(result.message),dual_qp_ftol=1e-12,
                dual_gap_source='pure_lasso_feasible_dual_and_complementarity')
            return
        if 'ridge_dual_factor' not in geometry:
            geometry['ridge_dual_factor'] = cho_factor(n*np.eye(n) + xc@xc.T/l2, lower=True)
        theta = cho_solve(geometry['ridge_dual_factor'], yc)
        theta -= theta.mean()
        target = self.tol*float(np.mean(yc*yc))*.01
        reductions, steps = 0, 0
        for steps in range(min(200, self.max_iter)+1):
            value, gradient, H, w = elastic_dual_state(theta, xc, yc, l1, l2, hessian=True)
            gap = float(np.dot(gradient,gradient)/(2.*n))
            if gap <= target or steps == min(200, self.max_iter):
                break
            direction = -cho_solve(cho_factor(H, lower=True), gradient)
            slope = float(np.dot(gradient,direction))
            step = 1.
            for backtrack in range(60):
                trial = theta + step*direction
                trial -= trial.mean()
                trial_value, _, _, _ = elastic_dual_state(trial, xc, yc, l1, l2)
                if trial_value <= value + 1e-4*step*slope:
                    theta = trial
                    reductions += backtrack
                    break
                step *= .5
            else:
                break
        _, gradient, _, w = elastic_dual_state(theta, xc, yc, l1, l2)
        self.coef_ = w
        self.intercept_ = float(values.mean()-geometry['mean']@w)
        self.dual_certificate_ = theta
        self.dual_gap_ = float(np.dot(gradient,gradient)/(2.*n))
        self.solver_mapping_.update(dual_newton_steps=steps, dual_newton_limit=min(200,self.max_iter),
            line_search_reductions=reductions, polish_gap_target=target,
            dual_gap_source='fenchel_dual_gradient_identity')

    def fit(self, X, y):
        self._validate_params()
        g = getattr(self, '_geometry', None)
        if g is None:
            g = regression_geometry(X, self.alpha, self.l1_ratio)
        if (g['rows'], g['augmented'].shape[1], g['alpha'], g['l1_ratio']) != (len(X), X.shape[1], self.alpha, self.l1_ratio):
            raise ValueError('Regression geometry context mismatch')
        values = np.asarray(y, float)
        centered = values - values.mean()
        augmented_y = np.concatenate([centered, np.zeros(len(g['augmented'])-len(values))])
        mapped_alpha = len(values) * self.alpha * self.l1_ratio / len(augmented_y)
        solver = LassoLars(alpha=mapped_alpha, fit_intercept=False, precompute=g['gram'].copy(),
            max_iter=self.max_iter, eps=np.finfo(float).eps, fit_path=False, jitter=None, random_state=self.random_state)
        solver.fit(g['augmented'], augmented_y)
        self.coef_ = np.asarray(solver.coef_, dtype=float).reshape(-1).copy()
        if len(self.coef_) != X.shape[1]:
            raise ValueError('Unexpected augmented single-target coefficient shape')
        self.intercept_ = float(values.mean() - g['mean'] @ self.coef_)
        self.n_features_in_, self.n_iter_ = X.shape[1], int(np.asarray(solver.n_iter_).max())
        if isinstance(X, pd.DataFrame):
            self.feature_names_in_ = np.asarray(X.columns, dtype=object)
        self.solver_mapping_ = dict(original_rows=len(values), augmented_rows=len(augmented_y),
            mapped_lasso_alpha=float(mapped_alpha), original_alpha=self.alpha, l1_ratio=self.l1_ratio,
            objective_multiplier=float(len(augmented_y)/len(values)), path_iterations=self.n_iter_)
        quality_parameters = dict(alpha=self.alpha, l1_ratio=self.l1_ratio, tol=self.tol)
        if not regression_quality(self, X, values, quality_parameters)['accepted']:
            self.polish(g, values)
        self.__dict__.pop('_geometry', None)  # bounded train-only workspace, never model state
        return self


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
                class_weight=self.policy['class_weight'], warm_start=True)
        regression = AugmentedLarsElasticNet if getattr(self, '_solver_attempt', 0) == 0 else ElasticNet
        return regression(alpha=p['alpha'], l1_ratio=p['l1_ratio'], tol=p['tol'],
            max_iter=max_iter, selection='cyclic', random_state=self.seed, warm_start=True)

    def solution_quality(self, estimator, X, y):
        if self.task == 'classification':
            return classification_quality(estimator, X, y, self.parameters, self.policy['class_weight'])
        return regression_quality(estimator, X, y, self.parameters)

    def _weight_identity(self):
        return digest(dict(fit=self.fit_context_, parameters=self.parameters, seed=self.seed,
            weights=weight_hash(self.estimators_), policy=self.policy,
            preprocessing_version=self.preprocessor.schema_['schema_version'],
            target_adapter_version=self.target_adapter.adapter_version_, quality_version=QUALITY_VERSION))

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
        self.input_diagnostics_ = input_diagnostics(X_train)
        geometry = None
        with threadpool_limits(limits=self.threads):
            for target, values in targets:
                fitted = None
                previous = None
                for attempt in range(self.policy['convergence_retries'] + 1):
                    maximum = self.parameters['max_iter'] * self.policy['iteration_multiplier'] ** attempt
                    self._solver_attempt = attempt
                    estimator = previous if previous is not None and self.task == 'classification' else self.estimator(maximum)
                    if previous is not None and self.task == 'classification':
                        estimator.set_params(max_iter=maximum, tol=self.parameters['tol'] / 10. ** attempt)
                    elif previous is not None and self.task == 'regression' and hasattr(estimator, 'set_params'):
                        estimator.set_params(tol=self.parameters['tol'] / 10. ** attempt)
                        estimator.coef_, estimator.intercept_ = previous.coef_.copy(), previous.intercept_
                    start = time.perf_counter()
                    if attempt == 0 and self.task == 'classification' and isinstance(estimator, LogisticRegression):
                        certificate = certify_zero_slopes(estimator, X_train, values, self.parameters,
                            self.policy['class_weight'])
                        if certificate is not None:
                            self.diagnostics_.append(dict(target=target, attempt=1, max_iter=maximum,
                                solver='certified_zero_slopes', solver_tolerance=None, estimator_fit_called=False,
                                elapsed_seconds=time.perf_counter() - start, quality=certificate,
                                input=self.input_diagnostics_, remedy='training_frequency_intercept_kkt_certificate',
                                n_iter=[0], dual_gap=[], numerical_failure=False, warnings=[], converged=True, nonzero=0))
                            fitted = estimator
                            break
                    if isinstance(estimator, AugmentedLarsElasticNet):
                        if geometry is None:
                            geometry = regression_geometry(X_train, self.parameters['alpha'], self.parameters['l1_ratio'])
                        estimator._geometry = geometry
                    with warnings.catch_warnings(record=True) as caught:
                        warnings.simplefilter('always')
                        try:
                            estimator.fit(X_train, values)
                        except BaseException as error:
                            self.diagnostics_.append(dict(target=target, attempt=attempt + 1,
                                max_iter=maximum, n_iter=None, dual_gap=[], nonzero=None, converged=False,
                                warnings=[{'category': w.category.__name__, 'message': str(w.message)} for w in caught],
                                elapsed_seconds=time.perf_counter() - start,
                                error=type(error).__name__ + ': ' + str(error)))
                            if not isinstance(error, Exception) or isinstance(error, (MemoryError, OSError)):
                                error.diagnostics = self.diagnostics_
                                raise
                            raise FitFailure('Estimator fit failed for ' + target + ': ' + str(error), self.diagnostics_) from error
                    warning_records = [{'category': w.category.__name__, 'message': str(w.message)} for w in caught]
                    nonfinite = not (np.isfinite(estimator.coef_).all() and np.isfinite(estimator.intercept_).all()
                        and np.isfinite(np.asarray(getattr(estimator, 'dual_gap_', []))).all())
                    warned_convergence = any(issubclass(w.category, ConvergenceWarning) for w in caught)
                    numerical = nonfinite or any(issubclass(w.category, RuntimeWarning) for w in caught)
                    quality = dict(accepted=False, reason='NONFINITE_SOLUTION') if numerical else self.solution_quality(estimator, X_train, values)
                    # A tightened continuation can exhaust its internal stopping
                    # budget after meeting the original independent gap criterion.
                    regression_certified = self.task == 'regression' and isinstance(estimator, ElasticNet) and quality['accepted']
                    convergence = warned_convergence and not regression_certified
                    self.diagnostics_.append(dict(target=target, attempt=attempt + 1, max_iter=maximum,
                        solver=getattr(estimator, 'solver_name', 'saga' if self.task == 'classification' else 'cyclic_coordinate_descent'),
                        solver_mapping=getattr(estimator, 'solver_mapping_', None),
                        preliminary_convergence_warning_resolved=warned_convergence and not convergence,
                        solver_tolerance=None if isinstance(estimator, AugmentedLarsElasticNet) else self.parameters['tol'] / 10. ** attempt,
                        elapsed_seconds=time.perf_counter() - start, quality=quality,
                        input=self.input_diagnostics_, remedy='equivalent_augmented_lars' if isinstance(estimator, AugmentedLarsElasticNet) else 'frequency_intercept_start' if attempt == 0 and self.task == 'classification' else 'warm_start_more_iterations_tighter_tolerance' if attempt else 'initial',
                        n_iter=np.asarray(estimator.n_iter_).tolist(),
                        dual_gap=np.where(np.isfinite(np.asarray(getattr(estimator, 'dual_gap_', []))),
                            np.asarray(getattr(estimator, 'dual_gap_', [])), None).tolist(), numerical_failure=numerical,
                        warnings=warning_records, converged=not convergence and not numerical and quality['accepted'],
                        nonzero=int(np.count_nonzero(estimator.coef_))))
                    if numerical:
                        raise FitFailure('Non-finite coefficients or numerical warning: ' + target, self.diagnostics_)
                    if not convergence and quality['accepted']:
                        fitted = estimator
                        break
                    # A bounded continuation retains work at the same parameters
                    # and seed; the independent acceptance thresholds stay fixed.
                    previous = estimator if hasattr(estimator, 'set_params') else None
                if fitted is None:
                    raise FitFailure('Convergence/optimality retries exhausted: ' + target, self.diagnostics_)
                self.estimators_.append(fitted)
        self.model_version_ = self._weight_identity()
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

    def dual_certificates(self):
        frames = []
        if self.task == 'regression':
            for target, estimator in zip(CORE, self.estimators_):
                if hasattr(estimator, 'dual_certificate_'):
                    frames.append(self.training_keys.assign(target=target, dual_value=estimator.dual_certificate_))
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

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
            solver_quality_version=QUALITY_VERSION, input_diagnostics=self.input_diagnostics_,
            calibrator=None, backend='cpu', model_family='elastic_net')
        manifest.update(library_versions=dict(sklearn=sklearn.__version__, scipy=scipy.__version__, numpy=np.__version__,
            pandas=pd.__version__, joblib=joblib.__version__), adapter_code_hash=file_hash(__file__),
            solver_code_hash=file_hash(Path(__file__).with_name('elastic_quality.py')),
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
        if manifest['library_versions'] != dict(sklearn=sklearn.__version__, scipy=scipy.__version__, numpy=np.__version__,
                pandas=pd.__version__, joblib=joblib.__version__) or manifest['adapter_code_hash'] != file_hash(__file__) or manifest['solver_code_hash'] != file_hash(Path(__file__).with_name('elastic_quality.py')) or manifest['interface_code_hash'] != code_hash():
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
        model.input_diagnostics_ = manifest['input_diagnostics']
        model.model_version_ = model._weight_identity()
        if model.model_version_ != manifest['model_version'] or key_hash(model.training_keys) != model.fit_context_['training_keys_hash']:
            raise ValueError('Model package weights mismatch')
        return model
