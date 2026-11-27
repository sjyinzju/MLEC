"""Random forests behind the shared checked prediction and persistence contract."""
from dataclasses import asdict
import json
from pathlib import Path
from time import perf_counter
import warnings

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from threadpoolctl import threadpool_limits

from ..common import CORE, digest
from ..model_contract import (classification_output, key_hash, package_manifest,
                              regression_output, validate_model_input, validate_output, validate_probabilities)
from ..preprocessing import FoldPreprocessor
from ..release import code_hash, file_hash
from ..target_adapters import TargetAdapter
from . import capabilities
from .errors import FitFailure
from .rbf_svm import libraries, model_code_hash
from .specifications import validate_parameters
from .svm_quality import array_state


FAMILY = 'random_forest'
WEIGHT_VERSION = 'forest-weights-v2'


def shrink_probabilities(native, prior, alpha):
    return (1 - alpha) * native + alpha * prior


def forest_probability_version(weights_version, alpha):
    return digest(dict(weights_version=weights_version, probability_alpha=alpha,
                       policy='natural_train_prior_shrinkage_v1'))


def _support_quantiles(values):
    return np.quantile(values, [0, .25, .5, .75, 1]).tolist()


class RandomForestAdapter:
    def __init__(self, *, task, preprocessor, target_adapter, training_keys, parameters,
                 seed, policy, threads=1, macro_lineage=None):
        if task not in ('classification', 'regression') or type(threads) is not int or threads < 1:
            raise ValueError('Two primary tasks and positive integer CPU threads required')
        validate_parameters(FAMILY, task, parameters)
        if policy['single_class'] != 'error' or policy['missing_class'] not in ('error', 'zero_for_absent'):
            raise ValueError('Explicit class policy required')
        self.task, self.preprocessor, self.target_adapter = task, preprocessor, target_adapter
        self.training_keys, self.parameters = training_keys.copy(), dict(parameters)
        self.seed, self.policy, self.threads = int(seed), dict(policy), threads
        self.macro_lineage = dict(macro_lineage or {})
        self.probability_alpha = float(self.parameters.get('probability_alpha', 0.))
        self.history_pseudocount = float(self.parameters.get('history_pseudocount', 1.))
        self.independent = self.parameters.get('regression_architecture') == 'independent'
        self.capabilities = capabilities(FAMILY, task)
        self.target_adapter.check_context(self.preprocessor.fit_context_)
        self.diagnostics_ = []

    def _check_fit_boundary(self, context):
        state = asdict(context)
        target_hash = state.pop('training_target_hash')
        if state != self.preprocessor.fit_context_ or key_hash(self.training_keys) != context.training_keys_hash:
            raise ValueError('Model fit differs from its input training context')
        self.target_adapter.check_context(context)
        if target_hash != self.target_adapter.context_['training_target_hash']:
            raise ValueError('Model/target training truth identity mismatch')

    def _target_values(self, y_train, n_rows):
        y = np.asarray(y_train)
        if self.task == 'regression':
            if y.shape != (n_rows, len(CORE)) or not np.isfinite(y).all():
                raise ValueError('Finite adapted seven-target matrix required')
            return y
        schema = self.target_adapter.schema_
        params = self.target_adapter.parameters_
        expected = {params['research_to_internal'][str(c)] for c in params['observed_classes']}
        if y.shape != (n_rows,) or not np.issubdtype(y.dtype, np.integer) or set(y) != expected:
            raise ValueError('One-dimensional internal hard classes from the fitted target adapter required')
        if len(expected) < 2 or (self.policy['missing_class'] == 'error' and len(expected) != len(schema['class_ids'])):
            raise FitFailure('Insufficient training classes under Random Forest class policy', [])
        return y

    def fit(self, X_train, y_train, context):
        self.__dict__.pop('model_version_', None)
        self.__dict__.pop('forest_weights_version_', None)
        self.diagnostics_ = []
        validate_model_input(X_train, self.preprocessor.schema_, keys=self.training_keys)
        self._check_fit_boundary(context)
        y = self._target_values(y_train, len(X_train))
        if not len(X_train.columns):
            raise FitFailure('Random Forest requires at least one transformed input column', [])
        options = {k: v for k, v in self.parameters.items()
                   if k not in {'probability_alpha', 'history_pseudocount', 'regression_architecture'}}
        options.update(bootstrap=True, random_state=self.seed, n_jobs=self.threads,
                       max_features=float(options['max_features']), max_samples=float(options['max_samples']))
        if self.task == 'classification':
            self._set_class_counts(np.bincount(y, minlength=len(self.target_adapter.schema_['class_ids'])))
            self.estimator_ = self._fit_forest(RandomForestClassifier(**options), X_train, y)
        elif self.independent:
            self.estimator_ = tuple(self._fit_forest(RandomForestRegressor(**options), X_train, y[:, j], target)
                                    for j, target in enumerate(CORE))
        else:
            self.estimator_ = self._fit_forest(RandomForestRegressor(**options), X_train, y)
        self.fit_context_ = asdict(context)
        self.forest_weights_version_ = self._weight_identity()
        self.model_version_ = self._prediction_identity()
        return self

    def _set_class_counts(self, counts):
        counts = np.asarray(counts)
        ids = self.target_adapter.schema_['class_ids']
        observed = self.target_adapter.parameters_['observed_classes']
        if (counts.shape != (len(ids),) or not np.issubdtype(counts.dtype, np.integer)
                or counts.min() < 0 or counts.sum() != len(self.training_keys)
                or [c for c, n in zip(ids, counts) if n] != observed):
            raise ValueError('Natural prior counts differ from the fitted class or training membership')
        self.training_class_counts_ = counts.tolist()
        weights = counts + self.history_pseudocount
        self.training_prior_ = weights / weights.sum()
        validate_probabilities(self.training_prior_[None, :], ids)
        if not (self.training_prior_ > 0).all():
            raise ValueError('Training prior must have full positive support')

    def _fit_forest(self, estimator, X, y, target=None):
        started = perf_counter()
        diagnostic = dict(component='estimator', phase='final', solver=FAMILY,
                          n_estimators=self.parameters['n_estimators'], threads=self.threads, warnings=[])
        if target is not None:
            diagnostic['target'] = target
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            try:
                # Forest joblib uses threads, while native libraries remain single-threaded.
                with threadpool_limits(limits=1):
                    estimator.fit(X, y)
            except Exception as error:
                diagnostic.update(status='FAILED', elapsed_seconds=perf_counter() - started, error=str(error))
                self.diagnostics_.append(diagnostic)
                raise FitFailure(str(error), self.diagnostics_) from error
            finally:
                diagnostic['warnings'] = [dict(category=w.category.__name__, message=str(w.message)) for w in caught]
        # A fixed accumulation order makes native predictions reproducible even after a parallel fit.
        estimator.set_params(n_jobs=1)
        self.diagnostics_.append(dict(diagnostic, status='SUCCEEDED', elapsed_seconds=perf_counter() - started))
        return estimator

    def _forests(self):
        return self.estimator_ if self.independent else (self.estimator_,)

    def _weight_identity(self):
        fields = ('children_left', 'children_right', 'feature', 'threshold', 'missing_go_to_left',
                  'value', 'n_node_samples', 'weighted_n_node_samples')
        trees = [[{name: array_state(getattr(tree.tree_, name)) for name in fields}
                  for tree in forest.estimators_] for forest in self._forests()]
        return digest(dict(family=FAMILY, version=WEIGHT_VERSION, fit=self.fit_context_, task=self.task,
                           input_schema=self.preprocessor.schema_['schema_version'],
                           target_adapter=self.target_adapter.adapter_version_,
                           parameters={k: v for k, v in self.parameters.items() if k != 'probability_alpha'},
                           seed=self.seed, policy=self.policy,
                           training_class_counts=getattr(self, 'training_class_counts_', None),
                           classes=getattr(self.estimator_, 'classes_', np.array([])).tolist(), trees=trees))

    def _prediction_identity(self):
        if self.task == 'classification':
            return forest_probability_version(self.forest_weights_version_, self.probability_alpha)
        return self.forest_weights_version_

    def set_probability_alpha(self, alpha):
        """Bind a selected postprocessor to an already fitted classification forest."""
        if self.task != 'classification' or not hasattr(self, 'forest_weights_version_'):
            raise ValueError('A fitted classification forest is required')
        parameters = dict(self.parameters, probability_alpha=alpha)
        validate_parameters(FAMILY, self.task, parameters)
        self.parameters = parameters
        self.probability_alpha = float(alpha)
        self.model_version_ = self._prediction_identity()

    def _check_prediction_boundary(self, X, context):
        if not hasattr(self, 'model_version_'):
            raise ValueError('Estimator is not fitted')
        validate_model_input(X, self.preprocessor.schema_, keys=context.keys)
        if context.model_id != FAMILY or context.model_version != self.model_version_:
            raise ValueError('Model family/weight identity mismatch')
        for field in ('fold_id', 'fit_cutoff', 'information_set', 'quality', 'versions'):
            if getattr(context, field) != self.fit_context_[field]:
                raise ValueError('Prediction context mismatch: ' + field)
        if not context.keys.market_id.eq(self.fit_context_['market_id']).all() or not (
                context.keys.asof_date.dt.to_period('M').astype(str).eq(context.fold_id).all()):
            raise ValueError('Prediction keys differ from fitted market/month')
        if context.preprocessing_version != self.preprocessor.schema_['schema_version'] or (
                context.target_adapter_version != self.target_adapter.adapter_version_):
            raise ValueError('Model component identity mismatch')

    def predict(self, X_predict, context):
        self._check_prediction_boundary(X_predict, context)
        schema = self.target_adapter.schema_
        if self.task == 'classification':
            p = shrink_probabilities(self._native_probabilities(X_predict), self.training_prior_, self.probability_alpha)
            output = classification_output(context, np.asarray(schema['class_ids'])[p.argmax(axis=1)], p, schema)
        else:
            output = regression_output(context, self.regression_values(X_predict), schema)
        return validate_output(output, context, task=self.task, schema=schema)

    def regression_values(self, X):
        """Original-unit values from a matrix already checked against this estimator's context."""
        if not len(X):
            values = np.empty((0, len(CORE)))
        elif self.independent:
            values = np.column_stack([forest.predict(X) for forest in self._forests()])
        else:
            values = self.estimator_.predict(X)
        return self.target_adapter.inverse_transform(values)

    def _native_probabilities(self, X):
        classes = self.estimator_.classes_
        native = self.estimator_.predict_proba(X) if len(X) else np.empty((0, len(classes)))
        return self.target_adapter.align_probabilities(native, classes, missing_policy=self.policy['missing_class'])

    def probability_evidence(self, X, output, *, key_columns):
        evidence = output[key_columns].copy()
        ids = self.target_adapter.schema_['class_ids']
        columns = ['predicted_state_prob_' + str(c) for c in ids]
        evidence[columns] = output[columns]
        native = self._native_probabilities(X) if self.probability_alpha else output[columns].to_numpy()
        evidence[['native_state_prob_' + str(c) for c in ids]] = native
        evidence[['train_history_prob_' + str(c) for c in ids]] = np.broadcast_to(self.training_prior_, native.shape)
        evidence['probability_alpha'] = self.probability_alpha
        if len(X):
            leaf_ids = self.estimator_.apply(X)
            support = np.column_stack([tree.tree_.n_node_samples[leaves]
                                       for tree, leaves in zip(self.estimator_.estimators_, leaf_ids.T)])
            evidence['minimum_tree_leaf_distinct_rows'] = support.min(axis=1)
            evidence['median_tree_leaf_distinct_rows'] = np.median(support, axis=1)
        else:
            evidence['minimum_tree_leaf_distinct_rows'] = pd.Series(dtype='int64')
            evidence['median_tree_leaf_distinct_rows'] = pd.Series(dtype='float64')
        return evidence

    def diagnostic_artifact(self):
        """Report split use and native node-level reduction in adapted target units."""
        columns = self.preprocessor.schema_['output_columns']
        counts = np.zeros(len(columns), dtype=np.int64)
        support, depth = [], []
        reduction = np.zeros(len(CORE))
        for j, forest in enumerate(self._forests()):
            for estimator in forest.estimators_:
                tree = estimator.tree_
                internal = tree.children_left >= 0
                counts += np.bincount(tree.feature[internal], minlength=len(columns))
                support.extend(tree.n_node_samples[~internal])
                depth.append(tree.max_depth)
                if self.task == 'regression':
                    left, right = tree.children_left[internal], tree.children_right[internal]
                    weights = tree.weighted_n_node_samples
                    difference = tree.value[left, :, 0] - tree.value[right, :, 0]
                    child_weight = weights[left] * weights[right] / weights[internal]
                    targets = slice(j, j + 1) if self.independent else slice(None)
                    reduction[targets] += (child_weight[:, None] * difference**2).sum(axis=0)
        group_counts = {}
        feature_counts = {}
        for column, count in zip(columns, counts):
            raw = column.removeprefix('missing__')
            if count:
                group = self.macro_lineage.get(raw, 'market')
                group_counts[group] = group_counts.get(group, 0) + int(count)
                feature_counts[column] = int(count)
        max_features = int(self._forests()[0].estimators_[0].max_features_)
        group_features = {}
        for column in columns:
            group = self.macro_lineage.get(column.removeprefix('missing__'), 'market')
            group_features[group] = group_features.get(group, 0) + 1
        report = dict(total_input_features=len(columns), input_feature_counts_by_group=group_features,
                      actual_features_per_split=max_features,
                      features_per_split_fraction=max_features / len(columns),
                      n_trees=len(depth), tree_depth_quantiles_0_25_50_75_100=_support_quantiles(depth),
                      leaf_distinct_rows_quantiles_0_25_50_75_100=_support_quantiles(support),
                      split_counts_by_feature=feature_counts, split_counts_by_group=group_counts,
                      macro_split_count=sum(n for g, n in group_counts.items() if g != 'market'))
        if self.task == 'regression':
            report.update(adapted_target_weights=dict(zip(CORE, self.target_adapter.parameters_['weight'])),
                          adapted_target_split_sse_reduction=dict(zip(CORE, reduction.tolist())),
                          adapted_target_split_sse_reduction_share=(
                              dict(zip(CORE, (reduction / reduction.sum()).tolist())) if reduction.sum() else None))
        return report

    def save(self, directory):
        directory = Path(directory)
        if not hasattr(self, 'model_version_'):
            raise ValueError('Estimator is not fitted')
        directory.mkdir(parents=True, exist_ok=False)
        self.preprocessor.save(directory / 'input')
        self.target_adapter.save(directory / 'target.json')
        self.training_keys.to_parquet(directory / 'training_keys.parquet', index=False)
        joblib.dump(self.estimator_, directory / 'estimator.joblib', compress=3)
        manifest = package_manifest(self.preprocessor, self.target_adapter, self.capabilities,
                                    model_version=self.model_version_)
        manifest.update(estimator_created=True, model_family=FAMILY, task=self.task,
                        parameters=self.parameters, seed=self.seed, policy=self.policy, threads=self.threads, backend='cpu',
                        diagnostics=self.diagnostics_, macro_lineage=self.macro_lineage, full_fit_context=self.fit_context_,
                        library_versions=libraries(), model_code_hash=model_code_hash(), interface_code_hash=code_hash())
        if self.task == 'classification':
            manifest['training_class_counts'] = self.training_class_counts_
        manifest['files'] = {p.relative_to(directory).as_posix(): file_hash(p)
                             for p in sorted(directory.rglob('*')) if p.is_file()}
        manifest['content_hash'] = digest(manifest)
        (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False),
                                                  encoding='utf8')

    @classmethod
    def load(cls, directory):
        directory = Path(directory).resolve()
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
        if digest({k: v for k, v in manifest.items() if k != 'content_hash'}) != manifest['content_hash']:
            raise ValueError('Model package manifest modified')
        if (manifest['model_family'] != FAMILY or manifest['library_versions'] != libraries()
                or manifest['model_code_hash'] != model_code_hash() or manifest['interface_code_hash'] != code_hash()):
            raise ValueError('Model package code/dependency versions differ')
        for name, sha in manifest['files'].items():
            path = (directory / name).resolve()
            if not path.is_relative_to(directory) or file_hash(path) != sha:
                raise ValueError('Model package component modified: ' + name)
        pre = FoldPreprocessor.load(directory / 'input')
        target = TargetAdapter.load(directory / 'target.json', context=pre.fit_context_)
        model = cls(task=manifest['task'], preprocessor=pre, target_adapter=target,
                    training_keys=pd.read_parquet(directory / 'training_keys.parquet'),
                    parameters=manifest['parameters'], seed=manifest['seed'], threads=manifest['threads'],
                    policy=manifest['policy'], macro_lineage=manifest['macro_lineage'])
        template = package_manifest(pre, target, model.capabilities, model_version=manifest['model_version'])
        if any(template[key] != manifest[key] for key in template if key != 'estimator_created'):
            raise ValueError('Model package schema mismatch')
        model.estimator_ = joblib.load(directory / 'estimator.joblib')
        expected_type = RandomForestClassifier if model.task == 'classification' else RandomForestRegressor
        forests = model._forests()
        if ((model.independent and (type(forests) is not tuple or len(forests) != len(CORE)))
                or any(type(forest) is not expected_type or forest.n_jobs != 1 for forest in forests)):
            raise ValueError('Model package estimator configuration mismatch')
        if model.task == 'classification':
            model._set_class_counts(manifest['training_class_counts'])
        model.fit_context_ = manifest['full_fit_context']
        model.diagnostics_ = manifest['diagnostics']
        model.forest_weights_version_ = model._weight_identity()
        model.model_version_ = model._prediction_identity()
        if model.model_version_ != manifest['model_version'] or (
                key_hash(model.training_keys) != model.fit_context_['training_keys_hash']):
            raise ValueError('Model package weights/training membership mismatch')
        return model
