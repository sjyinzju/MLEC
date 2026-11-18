"""Training-only internal time partitions. No DataStore or outer scoring reader."""
from copy import deepcopy
from dataclasses import asdict
import pandas as pd
from ..model_contract import fit_context, training_partition, key_hash
from .errors import FitFailure


class TrainingPartitions:
    def __init__(self, outer_train):
        self.context = asdict(fit_context(outer_train))
        self._train = deepcopy(outer_train)

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

    def outer_training(self):
        return deepcopy(self._train)
