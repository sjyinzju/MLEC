"""Generic paired calendar-block uncertainty, migrated from the prior framework."""
import numpy as np
import pandas as pd

def multiclass_losses(y, probabilities, class_ids):
    """Per-row proper scores; probabilities must follow the dictionary order."""
    y=np.asarray(y);p=np.asarray(probabilities,float);classes=list(class_ids)
    if p.shape!=(len(y),len(classes)) or not np.isfinite(p).all() or (p<0).any() or not np.allclose(p.sum(axis=1),1):
        raise ValueError('Invalid multiclass probabilities')
    if len(set(classes))!=len(classes) or not set(y)<=set(classes):raise ValueError('Unknown class order')
    index=np.array([classes.index(v) for v in y]);onehot=np.eye(len(classes))[index]
    return pd.DataFrame({'log_loss':-np.log(np.maximum(p[np.arange(len(y)),index],1e-15)),
                         'brier':((p-onehot)**2).sum(axis=1)})

def continuous_losses(observed, predicted):
    """Original-unit per-target errors; no whole-sample fitted scale."""
    a=np.asarray(observed,float);b=np.asarray(predicted,float)
    if a.shape!=b.shape or a.ndim!=2:raise ValueError('Unequal regression target dimensions')
    return {'absolute_error':np.abs(a-b),'squared_error':(a-b)**2}

def block_interval(values,dates,block_weeks=8,repetitions=500,seed=3059):
    """Resample contiguous calendar-week blocks, including weeks without samples."""
    values=np.asarray(values,float)
    weeks=pd.DatetimeIndex(dates).tz_localize(None).to_period('W').start_time
    calendar=pd.date_range(weeks.min(),weeks.max(),freq='7D')
    buckets=[values[weeks==w] for w in calendar];rng=np.random.default_rng(seed);means=[]
    n=len(calendar);width=min(block_weeks,n)
    for _ in range(repetitions):
        starts=rng.integers(0,n-width+1,size=int(np.ceil(n/width)))
        sampled=[buckets[i] for start in starts for i in range(start,start+width)][:n]
        v=np.concatenate(sampled)
        if len(v):means.append(float(v.mean()))
    return {'mean':float(values.mean()),'lower':float(np.quantile(means,.025)),'upper':float(np.quantile(means,.975)),
            'block_weeks':block_weeks,'repetitions':repetitions,'method':'moving_calendar_week_blocks'}
