"""Probability, paired calendar-block uncertainty, and event-level alarms."""
import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss,log_loss,roc_auc_score,average_precision_score,confusion_matrix

KEY=['sample_id','fold_id','horizon']

def probability_metrics(y,p):
    y=np.asarray(y,dtype=int);p=np.asarray(p,dtype=float)
    if len(p)!=len(y) or not np.isfinite(p).all() or ((p<0)|(p>1)).any(): raise ValueError('Invalid probabilities')
    binary=len(set(y))==2
    return {'n':len(y),'brier':float(brier_score_loss(y,p)),'log_loss':float(log_loss(y,p,labels=[0,1])),
            'roc_auc':float(roc_auc_score(y,p)) if binary else None,
            'pr_auc':float(average_precision_score(y,p)) if binary else None,
            'auc_reason':None if binary else 'Only one class observed',
            'confusion_at_0_5':confusion_matrix(y,p>=.5,labels=[0,1]).tolist()}

def reliability(y,p):
    d=pd.DataFrame({'y':y,'p':p});d['bin']=np.minimum((d.p*10).astype(int),9)
    return d.groupby('bin').agg(n=('y','size'),observed_rate=('y','mean'),mean_probability=('p','mean')).reset_index()

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

def paired_compare(m,z,**kwargs):
    if m.duplicated(KEY).any() or z.duplicated(KEY).any():raise ValueError('Duplicate paired keys')
    if set(map(tuple,m[KEY].to_numpy()))!=set(map(tuple,z[KEY].to_numpy())):raise ValueError('Unequal paired samples')
    d=m.merge(z,on=KEY,suffixes=('_m','_z'),validate='one_to_one').sort_values('asof_time_m')
    if not d.y_true_m.eq(d.y_true_z).all():raise ValueError('Unequal labels')
    for col in ['asof_time','fit_cutoff','sample_version','protocol_hash']:
        if not d[col+'_m'].eq(d[col+'_z']).all():raise ValueError('Unequal '+col)
    d['loss_difference']=(d.y_true_m-d.predicted_probability_m)**2-(d.y_true_z-d.predicted_probability_z)**2
    return d,block_interval(d.loss_difference,d.asof_time_m,**kwargs)

def choose_threshold(predictions,budget):
    """Maximize development true alarms subject to EACH calendar year's budget.

    This is a selected development operating point, not an unbiased evaluation.
    """
    if predictions.asof_time.dt.year.ge(2023).any():raise ValueError('Heldout threshold selection forbidden')
    candidates=np.r_[np.nextafter(1.,2.),np.unique(predictions.predicted_probability)]
    valid=[]
    for t in candidates:
        alarm=predictions.predicted_probability.ge(t)
        false=predictions.assign(false=alarm & predictions.y_true.eq(0)).groupby(predictions.asof_time.dt.year).false.sum()
        if false.max()<=budget:valid.append((int((alarm & predictions.y_true.eq(1)).sum()),-int(false.sum()),float(t)))
    return max(valid)[2]

def event_evaluate(predictions,episodes,mapping,threshold):
    p=predictions.copy();p['alarm']=p.predicted_probability.ge(threshold)
    events=episodes[(episodes.dimension=='combined') & episodes.onset_date.between('2020-01-01','2022-12-31')].copy()
    links=mapping[(mapping.dimension=='combined')&(mapping.horizon==20)&mapping.at_risk_at_prediction]
    links=links.merge(p[['sample_id','asof_time','alarm']],on='sample_id',validate='many_to_one')
    if not links.asof_time.dt.tz_localize(None).lt(links.onset_date).all():raise ValueError('Alarm opportunity on/after onset')
    rows=[]
    for e in events.itertuples():
        opp=links[links.episode_id==e.episode_id].sort_values('asof_time');alarms=opp[opp.alarm]
        # Only scored OOF opportunities count; boundary-purged opportunities remain absent.
        rows.append(dict(episode_id=e.episode_id,onset_date=e.onset_date,opportunities=len(opp),
             eligible=bool(len(opp)),full_20d_lead_window=bool(e.full_20d_lead_window),detected=bool(len(alarms)),
             lead_to_trigger=int(alarms.lead_to_trigger.iloc[0]) if len(alarms) else None,
             drawdown_at_alarm=float(alarms.current_drawdown_at_prediction.iloc[0]) if len(alarms) else None,
             repeated_alarms=max(0,len(alarms)-1)))
    rows=pd.DataFrame(rows);eligible=rows[rows.eligible];n=len(eligible);k=int(eligible.detected.sum())
    # Wilson interval uses unique events, never weekly observations; dependence caveat is reported.
    z=1.96;phat=k/n if n else 0;denom=1+z*z/n if n else 1
    center=(phat+z*z/(2*n))/denom if n else None
    half=z*np.sqrt(phat*(1-phat)/n+z*z/(4*n*n))/denom if n else None
    annual=p.assign(false=p.alarm&p.y_true.eq(0)).groupby(p.asof_time.dt.year).false.sum().to_dict()
    summary={'events':len(rows),'eligible_events':n,'detected_events':k,'detection_rate':k/n if n else None,
             'event_wilson_lower':center-half if n else None,'event_wilson_upper':center+half if n else None,
             'annual_false_alarm_weeks':{str(k):int(v) for k,v in annual.items()},'repeated_alarms':int(rows.repeated_alarms.sum()),
             'threshold':threshold,'threshold_evaluation':'development-selected, optimistic; freeze before final',
             'lead_mean':float(rows.lead_to_trigger.dropna().mean()) if rows.lead_to_trigger.notna().any() else None,
             'event_interval_caveat':'few unique events; Wilson assumes independent event detection; descriptive only'}
    return rows,summary
