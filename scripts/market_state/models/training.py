"""Training-only internal time partitions. No DataStore or outer scoring reader."""
from copy import deepcopy
from collections import OrderedDict
from dataclasses import asdict
import pandas as pd
from ..model_contract import fit_context, training_partition, key_hash, fit_inputs, transform_inputs
from ..target_adapters import fit_targets
from .svm_quality import array_state
from .errors import FitFailure


class TrainingPartitions:
    def __init__(self, outer_train):
        self.context = asdict(fit_context(outer_train))
        self._train = deepcopy(outer_train)
        self._cache = OrderedDict()
        self.cache_bytes = 0
        self.cache_limit = 64 * 1024**2
        self.cache_hits = self.cache_misses = 0

    def check_context(self, context):
        if asdict(context) != self.context:
            raise ValueError('Internal service is bound to another outer training cohort')

    def plan(self, rules):
        parent = self._train
        meta = parent.metadata
        dates = parent.keys.asof_date
        origin = dates.min().to_period('W-FRI').start_time
        start = origin + pd.Timedelta(weeks=rules['initial_train_weeks'])
        class_ids = parent.target_schema['class_ids']
        records = []
        while start <= dates.max():
            end = start + pd.Timedelta(weeks=rules['block_weeks'])
            cutoff = (start - pd.Timedelta(days=1)).tz_localize('Asia/Shanghai') + pd.Timedelta(hours=18)
            train_mask = meta.asof_time.le(cutoff) & meta.label_available_at.le(cutoff)
            validation_mask = dates.ge(start) & dates.lt(end)
            train_keys = parent.keys[train_mask].reset_index(drop=True)
            validation_keys = parent.keys[validation_mask].reset_index(drop=True)
            counts = parent.y.loc[train_mask, 'future_state_id'].value_counts().reindex(class_ids, fill_value=0)
            valid = len(train_keys) >= rules['min_train_rows'] and counts.ge(rules['min_train_per_class']).all() and len(validation_keys) > 0
            records.append(dict(block_id=len(records), start=str(start), end_exclusive=str(end), fit_cutoff=str(cutoff),
                status='ACCEPTED' if valid else 'SKIPPED',
                reason=None if valid else 'INSUFFICIENT_TRAIN_ROWS_OR_DICTIONARY_CLASS_SUPPORT_OR_EMPTY_BLOCK',
                train_rows=len(train_keys), validation_rows=len(validation_keys),
                class_counts={str(int(k)): int(v) for k, v in counts.items()},
                validation_class_counts={str(int(k)):int(v) for k,v in parent.y.loc[validation_mask,'future_state_id'].value_counts().reindex(class_ids,fill_value=0).items()},
                training_keys_hash=key_hash(train_keys), validation_keys_hash=key_hash(validation_keys)))
            start = end
        return records

    def partition(self, block):
        parent = self._train
        cutoff = pd.Timestamp(block['fit_cutoff'])
        train_mask = parent.metadata.asof_time.le(cutoff) & parent.metadata.label_available_at.le(cutoff)
        val_mask = parent.keys.asof_date.ge(pd.Timestamp(block['start'])) & parent.keys.asof_date.lt(pd.Timestamp(block['end_exclusive']))
        train = training_partition(parent, parent.keys[train_mask].reset_index(drop=True), role='train', fit_cutoff=cutoff)
        val = training_partition(parent, parent.keys[val_mask].reset_index(drop=True), role='validation', fit_cutoff=cutoff)
        if key_hash(train.keys) != block['training_keys_hash'] or key_hash(val.keys) != block['validation_keys_hash']:
            raise ValueError('Internal time block membership changed')
        return train, val

    def validate_plan(self, rules):
        plan = self.plan(rules)
        accepted = [b for b in plan if b['status'] == 'ACCEPTED']
        indices = []
        for b in accepted:
            mask = self._train.keys.asof_date.ge(pd.Timestamp(b['start'])) & self._train.keys.asof_date.lt(pd.Timestamp(b['end_exclusive']))
            indices.extend(self._train.y.loc[mask, 'future_state_id'].astype(int).tolist())
        counts = pd.Series(indices, dtype='int64').value_counts().reindex(self._train.target_schema['class_ids'], fill_value=0)
        if (len(accepted) < rules['min_accepted_blocks'] or len(indices) < rules['min_oof_rows'] or
                not counts.ge(rules['min_oof_per_class']).all() or not (len(indices) - counts).ge(rules['min_oof_per_class']).all()):
            raise FitFailure('Cannot form legal training-only time calibration', [])
        return plan

    def prepare_block(self, block):
        key = (block['training_keys_hash'], block['validation_keys_hash'], block['fit_cutoff'])
        if key in self._cache:
            self.cache_hits += 1
            self._cache.move_to_end(key)
            return self._cache[key][0]
        self.cache_misses += 1
        train, val = self.partition(block)
        pre, target = fit_inputs(train), fit_targets(train)
        xi, xv = transform_inputs(pre, train), transform_inputs(pre, val)
        result = dict(X=xi, X_validation=xv, y=target.transform(train.y), y_validation=target.transform(val.y),
            metadata=dict(preprocessing_version=pre.schema_['schema_version'], input_hash=array_state(xi),
                latest_train_label=str(train.metadata.label_available_at.max()),
                latest_validation_label=str(val.metadata.label_available_at.max())))
        size = int(xi.memory_usage(index=True,deep=True).sum()+xv.memory_usage(index=True,deep=True).sum())
        if size <= self.cache_limit:
            while self.cache_bytes+size > self.cache_limit:
                _, (_, old_size) = self._cache.popitem(last=False)
                self.cache_bytes -= old_size
            self._cache[key] = result, size
            self.cache_bytes += size
        return result

    def support_summary(self, plan):
        accepted=[b for b in plan if b['status']=='ACCEPTED']
        counts={str(c):sum(b['validation_class_counts'][str(c)] for b in accepted) for c in self._train.target_schema['class_ids']}
        n=sum(counts.values())
        return dict(class_counts=counts, rows=n, status='LEGAL_BUT_SPARSE_UNSTABLE' if min(min(v,n-v) for v in counts.values())<20 else 'LEGAL_SUPPORT_NOT_CALIBRATION_VALIDATION',
            oof_keys_hash=key_hash(self._train.keys[self._train.keys.asof_date.apply(lambda d:any(pd.Timestamp(b['start'])<=d<pd.Timestamp(b['end_exclusive']) for b in accepted))].reset_index(drop=True)))

    def outer_training(self):
        return deepcopy(self._train)
