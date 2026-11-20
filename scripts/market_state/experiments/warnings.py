"""Warning signals reuse state probabilities and drawdown; no learning model."""
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score
from ..common import CORE, KEY
from ..framework import load_dataset

# Signs orient predictions toward adverse movements. The turnover and
# correlation tails are activity and co-movement proxies, respectively.
ADVERSE_DIRECTION = dict(zip(CORE, [-1, 1, 1, 1, -1, 1, 1]))


def risk_definition(store, config):
    profiles = store.get('state_dictionary/profiles').sort_values('state_id')
    if profiles.label_version.nunique() != 1 or profiles.label_version.iloc[0] != store.spec['label_version']:
        raise ValueError('Risk profiles differ from fixed dictionary')
    definition = dict(dictionary_version=store.spec['label_version'],
        risks={flag: profiles.loc[profiles[flag], 'state_id'].astype(int).tolist() for flag in config['warning']['risk_flags']},
        class_drawdown={str(int(r.state_id)): float(r.drawdown) for r in profiles.itertuples()},
        source='fixed_initial_training_state_profiles')
    if config['model'] != 'elastic_net':
        return definition
    definition['state_profiles'] = profiles[['state_id'] + CORE].to_dict('records')
    definition['continuous_tail'] = {}
    definition['initial_class_frequency'] = {}
    definition['initial_class_support'] = []
    for market in config['markets']:
        data = load_dataset(market_id=market, fold_id='initial', role='train',
            task='regression', information_set='M', store=store, quality=config['quality'])
        cutoffs = {c: float((data.y[c] * ADVERSE_DIRECTION[c]).quantile(.9)) for c in CORE}
        definition['continuous_tail'][market] = dict(thresholds=cutoffs, quantile=.9,
            direction=ADVERSE_DIRECTION, source='initial_train', rows=len(data.keys))
        classes = load_dataset(market_id=market, fold_id='initial', role='train',
            task='classification', information_set='M', store=store, quality=config['quality'])
        counts = classes.y.future_state_id.value_counts().reindex(classes.target_schema['class_ids'], fill_value=0)
        definition['initial_class_frequency'][market] = {str(k): int(v) / len(classes.keys) for k, v in counts.items()}
        for label, count in counts.items():
            windows = classes.metadata.loc[classes.y.future_state_id.eq(label)]
            definition['initial_class_support'].append(dict(market_id=market, class_id=int(label),
                n=len(classes.keys), support=int(count), overlapping_window_clusters=window_clusters(windows)))
    return definition


def window_clusters(windows):
    dates = windows.sort_values('label_start')
    prior_end = dates.label_end.cummax().shift()
    return int((prior_end.isna() | dates.label_start.gt(prior_end)).sum())


def warning_data(scores, prediction_data, store, definition, task):
    if not len(scores):
        return pd.DataFrame(columns=KEY + ['signal', 'score', 'event', 'realized_drawdown', 'current_risk', 'current_score'])
    # This happens after model.predict and scoring; prediction itself never sees Y.
    truth = store.get('supervised_targets')
    extra = [c for c in ['future_state_id', 'drawdown', 'label_start', 'label_end'] if c not in scores]
    actual = scores.merge(truth[KEY + extra], on=KEY, how='left', validate='one_to_one') if extra else scores
    raw = pd.concat([prediction_data.keys, prediction_data.X], axis=1)
    raw = scores[KEY].merge(raw, on=KEY, validate='one_to_one')
    records = []
    for risk, classes in definition['risks'].items():
        if task == 'regression' and risk != 'risk_downside':
            continue
        signals = [(risk, actual[['predicted_state_prob_' + str(c) for c in classes]].sum(axis=1).to_numpy(),
                    raw[['current_state_prob_' + str(c) for c in classes]].sum(axis=1).to_numpy())] if task == 'classification' else [
                    ('predicted_drawdown', actual.predicted_drawdown.to_numpy(), raw.market__drawdown_20d.to_numpy())]
        if task == 'classification' and risk == 'risk_downside':
            drawdown = definition['class_drawdown']
            expected = sum(actual['predicted_state_prob_' + c].to_numpy() * v for c, v in drawdown.items())
            signals.append(('probability_weighted_drawdown', expected, raw.market__drawdown_20d.to_numpy()))
            if 'continuous_tail' in definition:
                signals.append(('state_0_probability', actual.predicted_state_prob_0.to_numpy(),
                    raw.current_state_prob_0.to_numpy()))
        for signal, values, current in signals:
            signal_classes = [0] if signal == 'state_0_probability' else classes
            frame = actual[KEY + ['label_start', 'label_end']].copy()
            frame['signal'], frame['risk_type'] = signal, risk
            frame['score'], frame['current_score'] = values, current
            frame['risk_change'] = frame.score - frame.current_score
            frame['current_risk'] = raw.current_state_id.isin(signal_classes).to_numpy()
            frame['event'] = actual.future_state_id.isin(signal_classes).to_numpy()
            frame['realized_drawdown'] = actual.drawdown.to_numpy()
            if not np.isfinite(frame[['score', 'current_score', 'realized_drawdown']].to_numpy(float)).all():
                raise ValueError('Non-finite warning signal or truth')
            records.append(frame)
    if task == 'regression' and 'continuous_tail' in definition:
        spec = definition['continuous_tail'][actual.market_id.iloc[0]]
        for column, threshold in spec['thresholds'].items():
            sign = spec['direction'][column]
            current = sign * raw['market__' + column + '_20d'].to_numpy()
            predicted = sign * actual['predicted_' + column].to_numpy()
            records.append(actual[KEY + ['label_start', 'label_end']].assign(
                signal='continuous_tail_' + column, risk_type='exploratory_continuous_tail',
                score=predicted, current_score=current, risk_change=predicted-current,
                current_risk=current >= threshold, event=(sign * actual[column]).to_numpy() >= threshold,
                realized_drawdown=actual.drawdown.to_numpy(), event_threshold=threshold))
    return pd.concat(records, ignore_index=True)


def select_workpoints(frame, burdens):
    if not len(frame):
        raise ValueError('No development warning windows')
    values = frame.score.to_numpy(float)
    if not np.isfinite(values).all():
        raise ValueError('Non-finite warning score')
    candidates = sorted(np.unique(values), reverse=True)
    points = []
    for burden in burdens:
        allowed = [v for v in candidates if (values >= v).mean() <= burden]
        threshold = float(min(allowed)) if allowed else None
        points.append(dict(target_burden=burden, threshold=threshold,
            development_burden=float((values >= threshold).mean()) if threshold is not None else 0.,
            development_events=int(frame.event.sum()) if 'event' in frame else None,
            source='development_only', selection='largest_attainable_burden_not_exceeding_target'))
    return points


def evaluate_workpoint(frame, threshold, *, ranking=True):
    values, events = frame.score.to_numpy(float), frame.event.to_numpy(bool)
    alarm = values >= threshold if threshold is not None else np.zeros(len(frame), dtype=bool)
    tp, fp, positives = int((alarm & events).sum()), int((alarm & ~events).sum()), int(events.sum())
    negatives, count = len(events) - positives, int(alarm.sum())
    ordered = frame.assign(alarm=alarm).sort_values('asof_date')
    weeks = pd.DatetimeIndex(ordered.asof_date).to_period('W').start_time.as_unit('ns')
    consecutive = np.r_[False, np.diff(weeks.asi8) == pd.Timedelta(weeks=1).value]
    a = ordered.alarm.to_numpy(bool)
    segments = int((a & ~(np.r_[False, a[:-1]] & consecutive)).sum())
    total = float(frame.realized_drawdown.sum())
    identifiable = positives > 0 and negatives > 0
    return dict(n=len(events), events=positives, alerts=count, tp=tp, fp=fp, missed=positives - tp,
        recall=float(tp / positives) if identifiable else None,
        precision=float(tp / count) if count and identifiable else None,
        false_positive_rate=float(fp / negatives) if identifiable else None,
        burden=float(count / len(events)) if len(events) else None,
        loss_coverage=float(frame.loc[alarm, 'realized_drawdown'].sum() / total) if total > 0 else None,
        alarm_segments=segments, repeat_alarm_windows=count - segments,
        increase=int((alarm & ~frame.current_risk.to_numpy(bool)).sum()),
        persistent=int((alarm & frame.current_risk.to_numpy(bool)).sum()),
        relief=int((~alarm & frame.current_risk.to_numpy(bool)).sum()),
        average_precision=float(average_precision_score(events, values)) if identifiable and ranking else None,
        roc_auc=float(roc_auc_score(events, values)) if identifiable and ranking else None,
        reason='DEFINED' if identifiable else 'NO_IDENTIFIABLE_EVENT_CONTRAST',
        process_definition='consecutive calendar alarm weeks; no crisis onset or lead-time claim')


def warning_curve(frame):
    thresholds = [None] + sorted(frame.score.unique().tolist(), reverse=True)
    # Ranking metrics summarize the whole score distribution and do not
    # depend on a threshold. Compute them once per curve.
    ranking = evaluate_workpoint(frame, None)
    return pd.DataFrame([dict(threshold=t, **{**evaluate_workpoint(frame, t, ranking=False),
        **{key: ranking[key] for key in ('average_precision', 'roc_auc')}}) for t in thresholds])
