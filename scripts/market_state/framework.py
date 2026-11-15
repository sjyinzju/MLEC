"""Shared full-state cohorts, synchronized folds and future evaluation contracts."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import RobustScaler
from sklearn.pipeline import make_pipeline
from .common import *

def build_framework(dictionary):
    from .dictionary import apply_dictionary
    future=read('future_window_outcomes');targets=apply_dictionary(future,dictionary,'future')
    frame('supervised_targets',targets)
    past=read('past_window_outcomes');current=apply_dictionary(past[past.window_length.eq(20)],dictionary,'current')
    frame('current_states',current)
    feature_cols=[c for c in CORE+['downside_semivol','worst_daily_return','worst_cumulative_return','up_day_fraction','path_slope','vol_concentration','return_dispersion','amount_cny','quote_coverage','return_coverage','float_coverage','suspension_fraction','unexplained_unquoted_fraction'] if c in past]
    features=future[KEY+['asof_time']].copy()
    for h in [5,20,60]:
        q=past[past.window_length.eq(h)][KEY+feature_cols].rename(columns={c:f'market__{c}_{h}d' for c in feature_cols})
        features=features.merge(q,on=KEY,validate='one_to_one')
    statecols=[c for c in current if c.startswith('current_state')]
    features=features.merge(current[KEY+statecols],on=KEY,validate='one_to_one')
    features['current_state_id']=features.current_state_id.astype(float)
    for lag in [1,2,4]:
        for col in ['current_state_id']+[c for c in statecols if 'prob_' in c]:
            features[col+f'_lag{lag}w']=features.groupby('market_id')[col].shift(lag)
    # Other markets' SAME-ASOF past information, never their future outcomes.
    cross=features[['market_id','asof_date']+[f'market__{c}_20d' for c in CORE]].pivot(index='asof_date',columns='market_id')
    cross.columns=['cross__'+m.replace('.','_')+'__'+c for c,m in cross.columns]
    features=features.merge(cross.reset_index(),on='asof_date',validate='many_to_one')
    features['feature_version']=VERSION;features['label_version']=dictionary['label_version'];frame('market_features',features)
    manifest=targets[KEY+['asof_time','label_available_at','measurement_valid','missing_reason','label_version']].copy()
    pastvalid=current.set_index(KEY).measurement_valid
    manifest['history_valid']=[bool(pastvalid.loc[tuple(k)]) for k in manifest[KEY].itertuples(index=False,name=None)]
    manifest['continuous_valid']=manifest.measurement_valid
    manifest['class_valid']=targets.future_state_id.notna()
    manifest['eligible']=manifest.history_valid&manifest.continuous_valid&manifest.class_valid
    manifest['period']=np.select([manifest.asof_date.dt.year.le(2019),manifest.asof_date.dt.year.le(2022)],['initial_train','development'],default='test')
    manifest['evaluation_eligible']=manifest.eligible & ~((manifest.period.eq('development')&targets.label_end.gt(pd.Timestamp('2022-12-31')))|(manifest.period.eq('initial_train')&targets.label_end.gt(pd.Timestamp('2019-12-31'))))
    manifest['eligibility_reason']=np.where(manifest.eligible,'AVAILABLE',manifest.missing_reason.where(manifest.missing_reason.ne(''),'CURRENT_WINDOW_INCOMPLETE'))
    frame('sample_manifest',manifest)
    rows=[];plans=[]
    # Initial training role is strictly mature by 2019 end. Development/test
    # windows are assigned by prediction date and scored only if fully mature.
    cut=clock('2019-12-31')
    for r in manifest[manifest.eligible&manifest.label_available_at.le(cut)].itertuples():
        rows.append({**{k:getattr(r,k) for k in KEY},'fold_id':'initial','role':'train','fit_cutoff':cut})
    for month in sorted(manifest.loc[manifest.asof_date.dt.year.ge(2020),'asof_date'].dt.to_period('M').unique()):
        prediction_dates=manifest.loc[manifest.asof_date.dt.to_period('M').eq(month),'asof_date'];first=prediction_dates.min()
        # Monthly fit before the first prediction day's open, using prior exchange close.
        cal=read('calendar').date;prior=cal[cal<month.start_time].max();cut=clock(prior)
        fold_id=str(month);role='validation' if month.year<=2022 else 'test'
        plans.append(dict(fold_id=fold_id,fit_cutoff=cut,prediction_start=first,prediction_end=prediction_dates.max(),period=role))
        train=manifest[manifest.eligible&manifest.label_available_at.le(cut)&manifest.asof_date.lt(first)]
        evaluation=manifest[manifest.evaluation_eligible&manifest.asof_date.dt.to_period('M').eq(month)]
        for part,rname in [(train,'train'),(evaluation,role)]:
            for r in part.itertuples():rows.append({**{k:getattr(r,k) for k in KEY},'fold_id':fold_id,'role':rname,'fit_cutoff':cut})
    frame('fold_membership',pd.DataFrame(rows));frame('time_splits',pd.DataFrame(plans))
    mcols=[c for c in features if c not in KEY+['asof_time','feature_version','label_version']]
    macro=read('macro/historical_reconstructed/features');zcols=[c for c in macro if c!='asof_date']
    specs=json.loads((OUT/'macro/specifications.json').read_text(encoding='utf8'))
    groups={g:[c for s in specs if s['series_group']==g for c in zcols if c.startswith('macro__'+s['series_id']+'__')] for g in ['growth','prices','credit','rates','external']}
    sets={'M':mcols,'M+Z':mcols+zcols,**{'M+Z_'+g:mcols+cols for g,cols in groups.items()}}
    write(OUT/'feature_sets.json',dict(version=VERSION,label_version=dictionary['label_version'],sets=sets,groups=groups,
        categorical_columns=[c for c in mcols if c=='current_state_id' or c.startswith('current_state_id_lag')],
        missing_policy='No whole-sample imputation/scaling; macro missingness does not remove rows; fit preprocessing within each training fold',
        paired_cohort='same sample_manifest and fold_membership for every information set and task'))

@dataclass
class Dataset:
    X: pd.DataFrame
    y: pd.DataFrame
    metadata: pd.DataFrame
    feature_names: list

def load_universe(market_id,asof):
    """Historical legal securities, with the actually observed member precision."""
    if market_id not in MARKETS:raise ValueError('Unknown market')
    t=pd.Timestamp(asof);date=t.tz_localize(None).normalize() if t.tzinfo else t.normalize()
    h=read('security_history');active=h[h.valid_from.le(date)&h.valid_to.gt(date)].copy()
    if market_id=='000985.SH':
        active['membership_precision']='historical_listing_intervals';return active.reset_index(drop=True)
    w=read('membership_snapshots');w=w[w.index_code.eq(market_id)&w.snapshot_date.le(date)]
    snap=w.snapshot_date.max()
    if pd.isna(snap) or (date-snap).days>45:return active.iloc[:0].assign(membership_precision='NO_RECENT_SNAPSHOT')
    codes=w[w.snapshot_date.eq(snap)].con_code
    # Alias lookup maps old observed codes to the same stable legal security.
    members=set(h[h.ts_code.isin(codes)].instrument_id)
    active=active[active.instrument_id.isin(members)].copy()
    active['snapshot_date']=snap;active['membership_precision']='observed_snapshot_max_45d_plus_known_listing_exits'
    return active.reset_index(drop=True)

def load_dataset(*,market_id=None,start=None,end=None,information_set='M',task='classification',fold_id=None,role=None,quality='historical_reconstructed',eligible_only=True):
    if task not in ['classification','probability','regression']:raise ValueError('Unknown task')
    if quality not in ['strict','historical_reconstructed','latest_at_retrieval']:raise ValueError('Unknown macro view')
    if (fold_id is None)!=(role is None):raise ValueError('fold_id and role must be specified together')
    if market_id is not None and market_id not in MARKETS:raise ValueError('Unknown market')
    spec=json.loads((OUT/'feature_sets.json').read_text(encoding='utf8'))
    if information_set not in spec['sets']:raise ValueError('Unknown information set')
    meta=read('sample_manifest');targets=read('supervised_targets')
    if eligible_only:meta=meta[meta.eligible]
    if market_id:meta=meta[meta.market_id.eq(market_id)]
    if start:meta=meta[meta.asof_date.ge(pd.Timestamp(start))]
    if end:meta=meta[meta.asof_date.le(pd.Timestamp(end))]
    if fold_id:
        folds=read('fold_membership');part=folds[folds.fold_id.eq(fold_id)&folds.role.eq(role)]
        if role not in ['train','validation','test'] or fold_id not in set(folds.fold_id):raise ValueError('Unknown fold/role')
        meta=meta.merge(part,on=KEY,validate='one_to_one')
        if role=='train' and not meta.label_available_at.le(meta.fit_cutoff).all():raise ValueError('Immature label')
    meta=meta.sort_values(['asof_date','market_id']).reset_index(drop=True)
    features=read('market_features').merge(read('macro/'+quality+'/features'),on='asof_date',validate='many_to_one')
    joined=meta[KEY].merge(features,on=KEY,validate='one_to_one')
    cols=spec['sets'][information_set];X=joined[cols].copy()
    ycols=['future_state_id'] if task=='classification' else [c for c in targets if c.startswith('future_state_prob_')] if task=='probability' else CORE
    y=meta[KEY].merge(targets[KEY+ycols],on=KEY,validate='one_to_one')[ycols]
    return Dataset(X,y,meta,cols)

def preprocessing():
    """An UNFITTED factory; caller must fit only on fold's train.X."""
    return make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),RobustScaler())

def paired_losses(left,right,*,task):
    """Future model-independent scoring interface; no predictions made here."""
    if left.duplicated(KEY).any() or right.duplicated(KEY).any():raise ValueError('Duplicate paired key')
    if set(map(tuple,left[KEY].to_numpy()))!=set(map(tuple,right[KEY].to_numpy())):raise ValueError('Unpaired rows')
    d=left.merge(right,on=KEY,suffixes=('_M','_MZ'),validate='one_to_one')
    for col in ['label_version','fit_cutoff','target_version']:
        if not d[col+'_M'].eq(d[col+'_MZ']).all():raise ValueError('Unpaired '+col)
    if task not in ['classification','probability','regression']:raise ValueError('Unknown task')
    d['loss_difference']=d.loss_M-d.loss_MZ
    return d
